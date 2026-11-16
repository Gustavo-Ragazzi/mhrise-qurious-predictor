-- Research probe for talisman melding (REFramework autorun script). Passive: it never calls game
-- functions that change state and never touches the save.
--
-- 1. "Discover" walks the type database from FacilityDataManager and writes every melding-related
--    type with its fields and methods to reframework/data/TalismanTypes.txt.
-- 2. It then hooks the melding lottery-like methods it found (names with lot/create/calc/pick/...)
--    plus via.Random, and records every call the game makes while you meld: arguments, return
--    values (lists are expanded), and each random draw with the generator it came from.
-- 3. Meld as usual, then press "Write log" -> reframework/data/TalismanTrace.txt.

local TYPES_OUT = "TalismanTypes.txt"
local TRACE_OUT = "TalismanTrace.txt"
local status = "idle"
local trace = {}
local depth = 0
local gen_index = {}
local hooked = {}
local hook_count = 0
local discovered = false

local MAKA = { [0] = "MakaAlchemy01", [1] = "MakaAlchemy02", [2] = "MakaAlchemy03", [3] = "MakaAlchemy04",
    [4] = "MakaAlchemy05", [11] = "MakaAlchemy06", [12] = "MakaAlchemy07", [13] = "MakaAlchemy08",
    [23] = "MakaAlchemy09", [24] = "MakaAlchemy10_C", [25] = "MakaAlchemy10_B", [26] = "MakaAlchemy10_A",
    [27] = "MakaAlchemy10_S" }

local PATTERN = { "lot", "Lot", "create", "Create", "calc", "Calc", "pick", "Pick", "select", "Select",
    "rand", "Rand", "exec", "Exec", "make", "Make", "decide", "Decide", "exclude", "Exclude", "check",
    "Check", "candidate", "Candidate", "start", "Start", "request", "Request", "reserve", "Reserve" }

local function try(f, ...)
    local ok, r = pcall(f, ...)
    if ok then return r end
    return nil
end

-- Each top-level hooked call is buffered and kept only if it drew a random number or is a
-- lottery/create call, so per-frame UI checks do not flood the log.
local buf = nil
local MAX_LINES = 300000
local function t(s)
    local line = string.rep("  ", depth) .. s
    if buf then buf[#buf + 1] = line elseif #trace < MAX_LINES then trace[#trace + 1] = line end
end
local function flush()
    if not buf then return end
    local keep = false
    for _, l in ipairs(buf) do
        if l:find("rng ", 1, true) or l:find("[> ][^%(]*[Ll]ot") or l:find("[Cc]reate") then keep = true break end
    end
    if keep then
        for _, l in ipairs(buf) do
            if #trace < MAX_LINES then trace[#trace + 1] = l end
        end
    end
    buf = nil
end

local function fdm() return sdk.get_managed_singleton("snow.data.FacilityDataManager") end

local function raw(obj)
    local p = {}
    for off = 0x10, 0x1c, 4 do
        local v = try(function() return obj:read_dword(off) end)
        p[#p + 1] = v and string.format("%08x", v & 0xffffffff) or "????????"
    end
    return table.concat(p, " ")
end

local function refresh_generators()
    gen_index = {}
    local m = fdm()
    if not m then return end
    for _, spec in ipairs({ { "_RandomManual", "M" }, { "_RandomAuto", "A" } }) do
        local arr = try(function() return m:get_field(spec[1]) end)
        local n = arr and arr:get_size() or 0
        for i = 0, n - 1 do
            local g = arr:get_element(i)
            if g then
                local tag = spec[2] .. i
                if spec[2] == "M" and MAKA[i] then tag = tag .. ":" .. MAKA[i] end
                gen_index[g:get_address()] = tag
            end
        end
    end
    local r = try(function() return m:get_field("_Random") end)
    if r then gen_index[r:get_address()] = "R" end
end

local function maka_states()
    local m = fdm()
    local arr = m and try(function() return m:get_field("_RandomManual") end)
    if not arr then return "?" end
    local out = {}
    for i, name in pairs(MAKA) do
        local g = arr:get_element(i)
        if g then out[#out + 1] = string.format("%s=%s", name, raw(g)) end
    end
    table.sort(out)
    return table.concat(out, " | ")
end

-- Value formatting ----------------------------------------------------------------------------

local function num(v)
    if type(v) == "number" then return v end
    if type(v) == "boolean" then return v and 1 or 0 end
    local m = try(function() return v:get_field("mValue") end)
    if type(m) == "number" then return m end
    m = try(function() return v:get_field("value__") end)
    if type(m) == "number" then return m end
    return nil
end

local function obj_fields(o)
    local td = try(function() return o:get_type_definition() end)
    if not td then return "?" end
    local parts = {}
    for _, f in ipairs(td:get_fields()) do
        if not f:is_static() then
            local v = try(function() return o:get_field(f:get_name()) end)
            local n = num(v)
            if n then
                parts[#parts + 1] = f:get_name():gsub("<(.-)>k__BackingField", "%1") .. "=" .. tostring(n)
            elseif v ~= nil then
                -- small numeric arrays / lists (rate tables, fixed skill lists)
                local size = try(function() return v:get_size() end)
                local items = size and v or nil
                if not size then
                    items = try(function() return v:get_field("mItems") or v:get_field("_items") end)
                    size = num(try(function() return v:get_field("mSize") or v:get_field("_size") end))
                end
                if size and items and size <= 12 then
                    local q = {}
                    for i = 0, size - 1 do
                        local e = try(function() return items:get_element(i) end)
                        q[#q + 1] = tostring(num(e) or (e and try(function() return e:call("get_SkillId") end)) or "?")
                    end
                    parts[#parts + 1] = f:get_name():gsub("<(.-)>k__BackingField", "%1") .. "=[" .. table.concat(q, " ") .. "]"
                end
            end
        end
    end
    return td:get_full_name() .. "{" .. table.concat(parts, ",") .. "}"
end

local function fmt_obj(o)
    if o == nil then return "null" end
    local td = try(function() return o:get_type_definition() end)
    if not td then return tostring(o) end
    local name = td:get_full_name()
    local size = try(function() return o:get_size() end)
    local items = size and o or nil
    if not size then
        local inner = try(function() return o:get_field("mItems") or o:get_field("_items") end)
        local cnt = num(try(function() return o:get_field("mSize") or o:get_field("_size") end))
        if inner and cnt then size, items = cnt, inner end
    end
    if size and items then
        local p = {}
        for i = 0, math.min(size, 160) - 1 do
            local e = try(function() return items:get_element(i) end)
            local n = num(e)
            if n then p[#p + 1] = tostring(n)
            elseif e ~= nil and try(function() return e:get_type_definition() end) then p[#p + 1] = obj_fields(e)
            else p[#p + 1] = tostring(e) end
        end
        return string.format("%s[%d]{%s}", name, size, table.concat(p, ";"))
    end
    local vt = try(function() return td:is_value_type() end)
    if vt then return tostring(num(o)) end
    return obj_fields(o)
end

local function fmt_arg(ptr, ptype)
    local is_value = ptype and try(function() return ptype:is_value_type() end)
    if is_value then
        local n = sdk.to_int64(ptr)
        local full = ptype:get_full_name()
        if full == "System.Single" then return tostring(sdk.to_float(ptr)) end
        return tostring(n & 0xffffffff)
    end
    local addr = sdk.to_int64(ptr)
    if addr == 0 then return "null" end
    local o = try(function() return sdk.to_managed_object(ptr) end)
    return o and fmt_obj(o) or string.format("0x%x", addr)
end

-- Discovery -----------------------------------------------------------------------------------

local function is_alchemy(name)
    return name and (name:find("lchemy") or name:find("Talisman") or name:find("Maka")) ~= nil
end

local function discover()
    local seen, queue, found = {}, {}, {}
    local function push(td)
        if not td then return end
        local name = try(function() return td:get_full_name() end)
        if not name or seen[name] then return end
        seen[name] = true
        queue[#queue + 1] = td
    end
    push(sdk.find_type_definition("snow.data.FacilityDataManager"))
    for _, n in ipairs({ "snow.data.alchemy.ReserveInfo", "snow.data.AlchemyPlSkillTableUserData",
        "snow.data.AlchemyPatturnUserData", "snow.data.alchemy.SkillGradeLotRateTableUserData",
        "snow.data.alchemy.SecondSkillLotRateTableUserData", "snow.data.alchemy.SlotNumTableUserData",
        "snow.data.alchemy.MysterySlotNumTableUserData", "snow.data.alchemy.RareTypeTableUserData",
        "snow.data.alchemy.GradeWorthTableUserData", "snow.data.alchemy.SlotWorthTableUserData",
        "snow.data.TalismanData", "snow.data.AlchemyFunction", "snow.data.AlchemyData",
        "snow.data.alchemy.AlchemyFunction", "snow.data.alchemy.AlchemyData", "snow.data.FacilityDataManager.Alchemy",
        "snow.gui.GuiAlchemy", "snow.gui.fsm.alchemy.GuiAlchemyFsmManager" }) do
        push(sdk.find_type_definition(n))
    end
    local lines = {}
    local i = 1
    while i <= #queue and i < 600 do
        local td = queue[i]
        i = i + 1
        local name = td:get_full_name()
        local keep = is_alchemy(name) or name == "snow.data.FacilityDataManager"
        if keep then
            found[#found + 1] = td
            lines[#lines + 1] = "TYPE " .. name
            for _, f in ipairs(try(function() return td:get_fields() end) or {}) do
                local ft = try(function() return f:get_type() end)
                lines[#lines + 1] = string.format("  field %s%s : %s", f:is_static() and "static " or "", f:get_name(),
                    ft and ft:get_full_name() or "?")
                push(ft)
            end
            for _, m in ipairs(try(function() return td:get_methods() end) or {}) do
                local ps = {}
                for _, pt in ipairs(try(function() return m:get_param_types() end) or {}) do
                    ps[#ps + 1] = pt:get_full_name()
                    push(pt)
                end
                local rt = try(function() return m:get_return_type() end)
                push(rt)
                lines[#lines + 1] = string.format("  method %s%s(%s) : %s", m:is_static() and "static " or "",
                    m:get_name(), table.concat(ps, ", "), rt and rt:get_full_name() or "?")
            end
            push(try(function() return td:get_parent_type() end))
        end
    end
    local f = io.open(TYPES_OUT, "w")
    f:write(table.concat(lines, "\n"), "\n")
    f:close()
    return found
end

-- Hooks ---------------------------------------------------------------------------------------

local function matches(name)
    if name:sub(1, 4) == "get_" or name:sub(1, 4) == "set_" then return false end
    for _, p in ipairs(PATTERN) do
        if name:find(p, 1, true) then return true end
    end
    return false
end

-- After these calls, dump state the call produced (the method returns void).
local POST = {
    ["filterSelectableSkillList"] = function(this, a1) return "SelectableSkillList=" .. fmt_obj(try(function() return this:get_field("<SelectableSkillList>k__BackingField") end)) end,
    ["removeSameSkill"] = function(this, a1) return "SelectableSkillList=" .. fmt_obj(try(function() return this:get_field("<SelectableSkillList>k__BackingField") end)) end,
    ["updateRandomSkillTableDataList"] = function(this, a1) return "RandomSkillTableList=" .. fmt_obj(try(function() return a1:get_field("<RandomSkillTableList>k__BackingField") end)) .. " Target=" .. fmt_obj(try(function() return a1:get_field("<TargetSkillTable>k__BackingField") end)) end,
    ["lotFirstSkill"] = function(this, a1) return "reserve=" .. obj_fields(a1) end,
    ["lotSecondSkill"] = function(this, a1) return "reserve=" .. obj_fields(a1) end,
    ["mysteryLotSlot"] = function(this, a1) return "reserve=" .. obj_fields(a1) end,
    ["lotSlot"] = function(this, a1) return "reserve=" .. obj_fields(a1) end,
    ["selectTargetSkill"] = function(this, a1) return "target=" .. fmt_obj(try(function() return this:get_field("<TargetSkillTableData>k__BackingField") end)) end,
}
local post_stack = {}
local active = nil   -- active-probe call log (compact), nil when idle
local RET_LOG = { lotSkillLv = true, lotGrade = true, checkActivateSecondSkillSlot = true }
local LIST_LOG = { filterSelectableSkillList = true, removeSameSkill = true }
local list_this = {}
KEEP = KEEP or {}    -- objects created by the active probe, kept referenced so they are never freed

local function hook_method(td, m)
    local key = td:get_full_name() .. "." .. m:get_name() .. "/" .. tostring(m:get_num_params())
    if hooked[key] then return end
    hooked[key] = true
    local static = m:is_static()
    local ptypes = try(function() return m:get_param_types() end) or {}
    local rtype = try(function() return m:get_return_type() end)
    local label = td:get_full_name():gsub("^snow%.data%.", "") .. "." .. m:get_name()
    local mname = m:get_name()
    local ok = pcall(sdk.hook, m, function(args)
        if active then
            active[#active + 1] = mname
            if LIST_LOG[mname] then
                local ps = {}
                for k = 3, 5 do ps[#ps + 1] = tostring(sdk.to_int64(args[k] or 0) & 0xffffffff) end
                if mname == "filterSelectableSkillList" then active[#active + 1] = "a=" .. table.concat(ps, ",") end
                list_this[#list_this + 1] = try(function() return sdk.to_managed_object(args[2]) end) or false
            end
            return
        end
        if depth == 0 then
            refresh_generators()
            buf = { "-- " .. os.date("%H:%M:%S") .. " states: " .. maka_states() }
        end
        local first = static and 2 or 3
        local ps = {}
        for k, pt in ipairs(ptypes) do
            ps[#ps + 1] = try(fmt_arg, args[first + k - 1], pt) or "?"
        end
        local this = static and "" or (try(function()
            local o = sdk.to_managed_object(args[2])
            return o and ("[" .. (num(try(function() return o:get_field("_Patturn") end)) or "") .. "]") or ""
        end) or "")
        t("> " .. label .. this .. "(" .. table.concat(ps, ", ") .. ")")
        local post = POST[m:get_name()]
        if post then
            local thiso = (not static) and try(function() return sdk.to_managed_object(args[2]) end) or nil
            local a1 = try(function() return sdk.to_managed_object(args[static and 2 or 3]) end)
            if post == POST["filterSelectableSkillList"] or post == POST["selectTargetSkill"] then
                t("  before: SelectableSkillList=" .. (try(post, thiso, a1) or "?"))
            end
            post_stack[#post_stack + 1] = { post, thiso, a1 }
        else
            post_stack[#post_stack + 1] = false
        end
        depth = depth + 1
    end, function(retval)
        if active then
            if mname == "randomU32" then
                active[#active + 1] = string.format("u=%d", sdk.to_int64(retval) & 0xffffffff)
            elseif LIST_LOG[mname] then
                local o = table.remove(list_this)
                local l = o and try(function() return o:get_field("<SelectableSkillList>k__BackingField") end)
                local ids = {}
                if l then
                    local items = try(function() return l:get_field("mItems") end) or try(function() return l:get_field("_items") end)
                    local n = num(try(function() return l:get_field("mSize") end) or try(function() return l:get_field("_size") end)) or 0
                    for i = 0, n - 1 do
                        local e = items:get_element(i)
                        ids[#ids + 1] = tostring(num(e:call("get_SkillId")))
                    end
                end
                active[#active + 1] = "L=" .. table.concat(ids, ",")
            elseif RET_LOG[mname] then
                active[#active + 1] = string.format("=%d", sdk.to_int64(retval) & 0xffffffff)
            end
            return retval
        end
        depth = math.max(0, depth - 1)
        local r = rtype and rtype:get_full_name() ~= "System.Void" and (try(fmt_arg, retval, rtype) or "?") or ""
        t("< " .. label .. (r ~= "" and (" = " .. r) or ""))
        local pe = table.remove(post_stack)
        if pe then t("  after: " .. (try(pe[1], pe[2], pe[3]) or "?")) end
        if depth == 0 then flush() end
        return retval
    end)
    if ok then hook_count = hook_count + 1 end
end

local function hook_rng(method)
    local m = sdk.find_type_definition("via.Random"):get_method(method)
    local this_ptr = {}
    pcall(sdk.hook, m, function(args)
        this_ptr[#this_ptr + 1] = sdk.to_int64(args[2])
    end, function(retval)
        local p = table.remove(this_ptr)
        local tag = p and gen_index[p] or "?"
        if depth > 0 or tag:find("Maka", 1, true) then
            local v = sdk.to_int64(retval)
            if method == "genF32" then v = sdk.to_float(retval) end
            t(string.format("  rng %s %s = %s", tag, method, method == "genF32" and tostring(v) or
                string.format("%d (%08x)", v & 0xffffffff, v & 0xffffffff)))
        end
        return retval
    end)
end

local function setup()
    local found = discover()
    refresh_generators()
    for _, td in ipairs(found) do
        if not td:get_full_name():find("gui", 1, true) then
            for _, m in ipairs(try(function() return td:get_methods() end) or {}) do
                local name = m:get_name()
                local alch = is_alchemy(td:get_full_name()) or is_alchemy(name)
                local full = td:get_full_name()
                local always = (full == "snow.data.alchemy.ReserveFunc" or full == "snow.data.alchemy.LotFunc")
                    and name:sub(1, 4) ~= "get_" and name:sub(1, 4) ~= "set_" and name:sub(1, 1) ~= "<" and name ~= ".ctor" and name:sub(1, 7) ~= "compare"
                if (alch and matches(name)) or always or POST[name] then pcall(hook_method, td, m) end
            end
        end
    end
    hook_rng("genU32")
    hook_rng("genF32")
    discovered = true
    status = string.format("discovered %d types, hooked %d methods (see data/%s)", #found, hook_count, TYPES_OUT)
end

local function write_log()
    local f = io.open(TRACE_OUT, "w")
    f:write(table.concat(trace, "\n"), "\n")
    f:close()
    status = string.format("written data/%s (%d lines)", TRACE_OUT, #trace)
end

-- Active probe ---------------------------------------------------------------------------------
-- Runs the game's own melding lottery (AlchemyFunction.lotFromReserveInfo) on a private
-- ReserveInfo for every melding method, many times in a row, logging each result with the
-- random values it used. reserveAlchemy (consumes materials) and outputFromReserveInfo (adds
-- talismans) are never called. Every generator is snapshotted first and restored at the end.

local ACTIVE_OUT = "TalismanActive4.txt"
-- Random-target methods first (Vigor = 10 is known safe with update), then methods where the
-- player picks the skill: those run only with a target (a null target crashes the game).
local RANDOM_PATTERNS = { 3, 4, 7, 8 }
local TARGET_PATTERNS = { 0, 1, 2, 9 }
local TRIALS = 150
local TRIALS_V2 = 60

local function all_gens()
    local out = {}
    local m = fdm()
    for _, spec in ipairs({ { "_RandomManual", "M" }, { "_RandomAuto", "A" } }) do
        local arr = m:get_field(spec[1])
        for i = 0, arr:get_size() - 1 do
            local g = arr:get_element(i)
            if g then out[#out + 1] = g end
        end
    end
    local r = m:get_field("_Random")
    if r then out[#out + 1] = r end
    return out
end

local function gen_snapshot()
    local s = {}
    for _, g in ipairs(all_gens()) do s[#s + 1] = { obj = g, sid = g:call("get_StateId"), raw = raw(g) } end
    return s
end

local function gen_restore(s)
    local bad = 0
    for _, e in ipairs(s) do
        e.obj:call("set_StateId", e.sid)
        if raw(e.obj) ~= e.raw then bad = bad + 1 end
    end
    return bad
end

local function maka_changes(before)
    local arr = fdm():get_field("_RandomManual")
    local out = {}
    for i = 0, arr:get_size() - 1 do
        local g = arr:get_element(i)
        if g and raw(g) ~= before[i] then out[#out + 1] = MAKA[i] or ("M" .. i) end
    end
    table.sort(out)
    return table.concat(out, ",")
end

local function maka_raw()
    local arr = fdm():get_field("_RandomManual")
    local s = {}
    for i = 0, arr:get_size() - 1 do
        local g = arr:get_element(i)
        if g then s[i] = raw(g) end
    end
    return s
end

local function list_items(list)
    local items = try(function() return list:get_field("mItems") end) or try(function() return list:get_field("_items") end)
    local n = num(try(function() return list:get_field("mSize") end) or try(function() return list:get_field("_size") end)) or 0
    local out = {}
    for i = 0, n - 1 do
        local e = items and items:get_element(i)
        if e then out[#out + 1] = e end
    end
    return out
end

local function targets_for(func, p)
    local lists = func:get_field("<SkillTableList>k__BackingField")
    local by_grade = {}
    for li = 0, (lists and lists:get_size() or 0) - 1 do
        for _, e in ipairs(list_items(lists:get_element(li))) do
            if num(e:call("get_Patturn")) == p and (num(e:call("get_PickRate")) or 0) > 0 then
                local gr = num(e:call("get_Grade")) or -1
                by_grade[gr] = by_grade[gr] or {}
                table.insert(by_grade[gr], e)
            end
        end
    end
    local out = {}
    for gr = 0, 3 do
        local l = by_grade[gr]
        if l then
            out[#out + 1] = l[1]
            if #l > 2 then out[#out + 1] = l[math.floor(#l / 2) + 1] end
        end
    end
    return out
end

local function new_reserve()
    local ri = sdk.create_instance("snow.data.alchemy.ReserveInfo")
    if not ri then error("create_instance ReserveInfo failed") end
    ri = ri:add_ref()
    KEEP[#KEEP + 1] = ri
    if not try(function() return ri:get_field("<FixedSkillIdList>k__BackingField") end) then pcall(function() ri:call(".ctor") end) end
    if not try(function() return ri:get_field("<RandomSkillTableList>k__BackingField") end) then
        local arr = sdk.create_managed_array("snow.data.AlchemyPlSkillTableData", 2):add_ref()
        KEEP[#KEEP + 1] = arr
        ri:call("set_RandomSkillTableList", arr)
    end
    return ri
end

local function run_active()
    if not discovered then setup() end
    local func = fdm():get_field("_AlchemyFacility"):get_field("_Function")
    local snap = gen_snapshot()
    refresh_generators()
    local fh = io.open(ACTIVE_OUT, "w")
    local nlines = 0
    local out = setmetatable({}, { __newindex = function(_, _, v)
        fh:write(v, "\n")
        fh:flush()
        nlines = nlines + 1
    end, __len = function() return nlines end })
    out[1] = "== active probe v4 " .. os.date("%Y-%m-%d %H:%M:%S")
    local rf = func:get_field("_ReserveFunc")
    local old_sel = try(function() return rf:call("get_SelectPatturn") end)
    local old_target = try(function() return rf:call("get_TargetSkillTableData") end)
    for _, pd in ipairs(list_items(func:get_field("<UiPatturnDataList>k__BackingField")) or {}) do
        out[#out + 1] = string.format("NAME %s %s | %s", tostring(num(pd:call("getPatturn"))),
            tostring(try(function() return pd:call("getName") end)), tostring(try(function() return pd:call("get_NameMR") end)))
    end
    local ri = new_reserve()
    local ok, err = pcall(function()
        local plan = {}
        for _, p in ipairs(RANDOM_PATTERNS) do plan[#plan + 1] = { p, false } end
        for _, p in ipairs(TARGET_PATTERNS) do plan[#plan + 1] = { p, true } end
        for _, step in ipairs(plan) do
            local p = step[1]
            pcall(function() rf:call("set_SelectPatturn", p) end)
            local runs = {}
            if step[2] then
                for _, tg in ipairs(targets_for(func, p)) do runs[#runs + 1] = tg end
            else
                runs[1] = false
            end
            for _, tg in ipairs(runs) do
                local tlabel = tg and string.format("%d/g%d", num(tg:call("get_SkillId")), num(tg:call("get_Grade"))) or "-"
                out[#out + 1] = string.format("PAT %d TARGET %s START %s", p, tlabel, maka_states())
                if tg then out[#out + 1] = "ROW " .. obj_fields(tg) end
                pcall(function() rf:call("set_TargetSkillTableData", tg or nil) end)
                for i = 1, TRIALS_V2 do
                    pcall(function() ri:call("initResultParam") end)
                    ri:set_field("PatturnType", p)
                    ri:set_field("CreateNum", 1)
                    ri:set_field("MaxOutputNum", 1)
                    pcall(function() ri:call("set_MaxSlotNum", 3) end)
                    pcall(function() ri:call("set_MysteryWorth", 0) end)
                    pcall(function() ri:call("set_TargetSkillTable", tg or nil) end)
                    local before = maka_raw()
                    active = {}
                    local cok, cerr = pcall(function()
                        rf:call("updateRandomSkillTableDataList", ri)
                        func:call("lotFromReserveInfo", ri)
                    end)
                    local calls = active
                    active = nil
                    out[#out + 1] = string.format("T %d gen=%s calls=%s res=%s%s", i, maka_changes(before),
                        table.concat(calls, " "), obj_fields(ri), cok and "" or (" ERR " .. tostring(cerr)))
                    if not cok and i > 3 then break end
                end
            end
        end
    end)
    active = nil
    pcall(function() rf:call("set_SelectPatturn", old_sel) end)
    pcall(function() rf:call("set_TargetSkillTableData", old_target) end)
    local bad = gen_restore(snap)
    out[#out + 1] = string.format("== restored %d generators, %d mismatches%s", #snap, bad, ok and "" or (", error: " .. tostring(err)))
    fh:close()
    status = string.format("active probe DONE: %d lines -> data/%s; restore mismatches %d%s", nlines, ACTIVE_OUT, bad, ok and "" or " (ERROR, see file)")
end

re.on_draw_ui(function()
    if imgui.tree_node("Talisman trace") then
        imgui.text(status)
        if not discovered and imgui.button("Discover + hook") then
            local ok, err = pcall(setup)
            if not ok then status = "error: " .. tostring(err) end
        end
        imgui.text(string.format("trace lines: %d", #trace))
        if imgui.button("Write log") then pcall(write_log) end
        if imgui.button("Clear") then trace = {} end
        if imgui.button("Run active probe (all methods)") then
            status = "active probe running..."
            local ok, err = pcall(run_active)
            active = nil
            if not ok then status = "active error: " .. tostring(err) end
        end
        imgui.tree_pop()
    end
end)
