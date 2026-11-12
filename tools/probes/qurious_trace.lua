-- Research probe #2 for the qurious crafting logic (REFramework autorun script).
--
-- Open Qurious Crafting at the smithy, pick an armor piece (augmentation enabled), then press
-- "Run trace" in the "Qurious trace" menu. The probe:
--   * dumps the selected armor's buildup tables;
--   * calls each lottery function (lotCategory, lotValueIndex, lotCustomBuildupIndex, lotSkillId,
--     createResult) many times from known generator states (via.Random:init(i)) and logs inputs,
--     outputs and generator state before/after; RNG draws are traced through hooks;
--   * snapshots and RESTORES every FacilityDataManager generator afterwards.
-- It also logs, passively, every createResult call the game itself makes (e.g. a real augment),
-- with the generator state at that moment. Do not save the game after testing.
--
-- Output: <game>/reframework/data/QuriousTrace.txt

local OUT = "QuriousTrace.txt"
local status = "idle"
local L = {}
local tracing = false
local depth = 0
local gen_index = {}     -- via.Random address -> "M32", "A3", "R"
local passive = {}       -- passive log lines (game-initiated createResult calls)

local function w(s) L[#L + 1] = s end
local function try(f, ...)
    local ok, r = pcall(f, ...)
    if ok then return r end
    return nil
end

local function num(v)
    if v == nil then return nil end
    if type(v) == "number" then return v end
    if type(v) == "boolean" then return v and 1 or 0 end
    local m = try(function() return v:get_field("mValue") end)
    if type(m) == "number" then return m end
    m = try(function() return v.value__ end) or try(function() return v:get_field("value__") end)
    if type(m) == "number" then return m end
    local s = try(function() return v:call("ToString()") end)
    return s and tonumber(s) or nil
end

local function raw(obj)
    local p = {}
    for off = 0x10, 0x1c, 4 do
        local v = try(function() return obj:read_dword(off) end)
        p[#p + 1] = v and string.format("%08x", v & 0xffffffff) or "????????"
    end
    return table.concat(p, "")
end

-- Generic dump of an object's instance fields (numbers, arrays, lists, nested objects).
local function dump(obj, ind, d)
    if obj == nil then w(ind .. "nil") return end
    local td = try(function() return obj:get_type_definition() end)
    if not td then w(ind .. tostring(num(obj) or obj)) return end
    for _, f in ipairs(td:get_fields()) do
        if not f:is_static() then
            local name = f:get_name()
            local v = try(function() return obj:get_field(name) end)
            local n = (type(v) == "number" or type(v) == "boolean") and num(v) or nil
            if n then
                w(string.format("%s%s = %s", ind, name, tostring(n)))
            elseif v == nil then
                w(string.format("%s%s = nil", ind, name))
            else
                local size = try(function() return v:get_size() end)
                local items = size and v or nil
                if not size then
                    local inner = try(function() return v:get_field("_items") end)
                    local cnt = try(function() return v:get_field("_size") end)
                    if inner and cnt then size, items = num(cnt), inner end
                end
                if size and items then
                    local nums, objs = {}, {}
                    for i = 0, size - 1 do
                        local e = try(function() return items:get_element(i) end)
                        local en = (type(e) == "number") and e or (e and try(function() return e:get_type_definition():is_value_type() end) and num(e))
                        if en then nums[#nums + 1] = tostring(en) else objs[#objs + 1] = e end
                    end
                    w(string.format("%s%s [%d] %s", ind, name, size, table.concat(nums, ",")))
                    if d > 0 then
                        for i, e in ipairs(objs) do
                            w(string.format("%s  #%d", ind, i - 1))
                            dump(e, ind .. "    ", d - 1)
                        end
                    end
                elseif d > 0 and try(function() return v:get_type_definition() end) then
                    local vt = try(function() return v:get_type_definition():is_value_type() end)
                    if vt then
                        w(string.format("%s%s = %s", ind, name, tostring(num(v))))
                    else
                        w(string.format("%s%s:", ind, name))
                        dump(v, ind .. "  ", d - 1)
                    end
                else
                    w(string.format("%s%s = %s", ind, name, tostring(num(v) or v)))
                end
            end
        end
    end
end

-- Generators ----------------------------------------------------------------------------------

local function fdm() return sdk.get_managed_singleton("snow.data.FacilityDataManager") end

local function all_generators()
    local out = {}
    local m = fdm()
    local function add(arr, tag)
        local n = arr and arr:get_size() or 0
        for i = 0, n - 1 do
            local g = arr:get_element(i)
            if g then out[#out + 1] = { tag = tag .. i, obj = g } end
        end
    end
    add(m:get_field("_RandomManual"), "M")
    add(m:get_field("_RandomAuto"), "A")
    local r = m:get_field("_Random")
    if r then out[#out + 1] = { tag = "R", obj = r } end
    return out
end

local function snapshot()
    local s = {}
    gen_index = {}
    for _, g in ipairs(all_generators()) do
        s[#s + 1] = { obj = g.obj, sid = g.obj:call("get_StateId"), raw = raw(g.obj) }
        gen_index[g.obj:get_address()] = g.tag
    end
    return s
end

local function restore(s)
    local bad = 0
    for _, e in ipairs(s) do
        e.obj:call("set_StateId", e.sid)
        if raw(e.obj) ~= e.raw then bad = bad + 1 end
    end
    return bad
end

-- Hooks ---------------------------------------------------------------------------------------

local function arg_int(a) return a and (sdk.to_int64(a) & 0xffffffff) or -1 end

local function hook(typename, method, nargs, static)
    local td = sdk.find_type_definition(typename)
    local m = td and td:get_method(method)
    if not m then w("hook: missing " .. typename .. "." .. method) return end
    local first = static and 2 or 3
    local ok = pcall(sdk.hook, m, function(args)
        if not tracing then return end
        local ps = {}
        for k = first, first + nargs - 1 do ps[#ps + 1] = tostring(arg_int(args[k])) end
        w(string.rep("  ", depth) .. "> " .. method .. "(" .. table.concat(ps, ",") .. ")")
        depth = depth + 1
    end, function(retval)
        if tracing then
            depth = math.max(0, depth - 1)
            w(string.rep("  ", depth) .. "< " .. method .. " = " .. tostring(arg_int(retval)))
        end
        return retval
    end)
    if not ok then w("hook failed: " .. method) end
end

local function hook_rng(method)
    local m = sdk.find_type_definition("via.Random"):get_method(method)
    local this_ptr = {}
    local ok = pcall(sdk.hook, m, function(args)
        if tracing then this_ptr[#this_ptr + 1] = sdk.to_int64(args[2]) end
    end, function(retval)
        if tracing then
            local p = table.remove(this_ptr)
            local tag = p and gen_index[p] or "?"
            local v = sdk.to_int64(retval)
            w(string.rep("  ", depth) .. string.format("  rng %s %s = %d", tag, method, v & 0xffffffffffffffff))
        end
        return retval
    end)
    if not ok then w("rng hook failed: " .. method) end
end

local hooks_installed = false
local function install_hooks()
    if hooks_installed then return end
    hooks_installed = true
    hook("snow.data.ArmorCustomBuildupData", "lotCategory", 1, false)
    hook("snow.data.ArmorCustomBuildupData", "lotCustomBuildupIndex", 4, false)
    hook("snow.data.ArmorCustomBuildupData", "getBuildupCategoryByType", 2, false)
    hook("snow.data.ArmorCustomBuildupData", "getBuildupIdListByType", 2, false)
    hook("snow.data.CustomBuildupBaseUserData.Param", "lotValueIndex", 1, false)
    hook("snow.data.CustomBuildupData", "createResult", 3, false)
    hook("snow.data.CustomBuildupModule", "lotSkillId", 2, true)
    hook_rng("genU32")
    hook_rng("genF32")
    hook_rng("genF64")

    -- Passive: log createResult calls made by the game (or other mods) with the live state.
    local m = sdk.find_type_definition("snow.data.ArmorCustomBuildupData"):get_method("createResult")
    pcall(sdk.hook, m, function(args)
        if tracing then return end
        local seed = arg_int(args[8])
        local g = try(function() return fdm():get_field("_RandomManual"):get_element(seed) end)
        passive[#passive + 1] = string.format("game createResult(cost=%d, slotBlank=%d, isSort=%d, type=%d, seed=%d) table=%d state=%s",
            arg_int(args[3]), arg_int(args[4]), arg_int(args[6]) & 0xff, arg_int(args[7]) & 0xff, seed,
            num(try(function() return sdk.to_managed_object(args[2]):get_field("_TableNo") end)) or -1,
            g and raw(g) or "?")
    end, function(retval) return retval end)
end

-- Experiments ---------------------------------------------------------------------------------

local function result_str(arr)
    if not arr then return "nil" end
    local parts = {}
    for i = 0, arr:get_size() - 1 do
        local r = arr:get_element(i)
        parts[#parts + 1] = string.format("%d/%d/v%d/s%d/c%d", num(r:call("get_CategoryId")) or -1,
            num(r:call("get_Id")) or -1, num(r:call("get_Value")) or -1,
            num(r:call("get_PlSkillId")) or -1, num(r:call("get_Cost")) or -1)
    end
    return table.concat(parts, " ")
end

local function list_str(list)
    if not list then return "nil" end
    local items = try(function() return list:get_field("_items") end)
    local n = num(try(function() return list:get_field("_size") end)) or 0
    local p = {}
    for i = 0, n - 1 do p[#p + 1] = tostring(num(items:get_element(i))) end
    return "[" .. table.concat(p, ",") .. "]"
end

local function trial(gen, i, label, f)
    gen:call("init", i)
    local before = raw(gen)
    local ok, res = pcall(f)
    w(string.format("%s i=%d pre=%s ret=%s post=%s", label, i, before, ok and tostring(res) or ("ERR " .. tostring(res)), raw(gen)))
end

local SEED = 32

local function run()
    L = {}
    install_hooks()
    local smithy = sdk.get_managed_singleton("snow.gui.fsm.smithy.GuiSmithyFsmManager")
    local inv = smithy and smithy:call("get_CustomBuildupInventoryData")
    if not inv then status = "open Qurious Crafting and select an armor piece first" return end

    local armor = inv:call("getArmorData")
    local base = inv:call("getArmorBaseData")
    local tableNo = num(armor:call("get_CustomTableNo"))
    local cost = num(armor:call("get_CustomCost"))
    local slots = armor:call("getOriginalSlotLvTable")
    local s0, s1, s2 = num(slots:get_element(0)), num(slots:get_element(1)), num(slots:get_element(2))
    local slotBlank = 12 - s0 - s1 - s2
    local skills = base:call("get_AllSkillDataList")
    local acd = sdk.get_managed_singleton("snow.data.CustomBuildupModule"):getArmorData(tableNo)
    local gui = sdk.get_managed_singleton("snow.gui.GuiManager"):call("get_refGuiCustomBuildup")
    local uiType = gui and num(gui:call("get_BuildupType"))

    w(string.format("== armor %s id=%s table=%d cost=%d slots=%d,%d,%d slotBlank=%d uiType=%s",
        tostring(armor:call("getName")), tostring(num(armor:call("get_Id"))), tableNo, cost, s0, s1, s2, slotBlank, tostring(uiType)))
    w("== base skills")
    dump(skills, "  ", 2)
    w("== ArmorCustomBuildupData")
    dump(acd, "  ", 3)
    local cl = sdk.find_type_definition("snow.data.ArmorCustomBuildupData"):get_field("CategoryList"):get_data(nil)
    local cats = {}
    for i = 0, (cl and cl:get_size() or 0) - 1 do cats[#cats + 1] = num(cl:get_element(i)) end
    w("CategoryList = " .. table.concat(cats, ","))

    local snap = snapshot()
    local gen = fdm():get_field("_RandomManual"):get_element(SEED)
    local ACD = sdk.find_type_definition("snow.data.ArmorCustomBuildupData")
    local MOD = sdk.find_type_definition("snow.data.CustomBuildupModule")
    tracing = true

    w("== type tables (deterministic)")
    for t = 0, 3 do
        for lc = 0, 7 do
            local c = try(function() return ACD:get_method("getBuildupCategoryByType"):call(acd, t, lc) end)
            local ids = try(function() return ACD:get_method("getBuildupIdListByType"):call(acd, t, lc) end)
            w(string.format("type=%d lotCount=%d category=%s ids=%s", t, lc, tostring(num(c)), list_str(ids)))
        end
    end

    w("== lotCategory")
    for i = 1, 200 do
        trial(gen, i, "lotCategory", function() return num(ACD:get_method("lotCategory"):call(acd, SEED)) end)
    end

    w("== lotValueIndex (first buildup of every category)")
    local dict = acd:get_field("_DataDict")
    for _, c in ipairs(cats) do
        local list = try(function() return dict:call("get_Item", c) end)
        local items = list and try(function() return list:get_field("_items") end)
        local n = list and num(list:get_field("_size")) or 0
        w(string.format("category %d: %d buildups", c, n))
        for k = 0, n - 1 do
            local bd = items:get_element(k)
            local bp = bd:get_field("_BaseParam")
            w(string.format("  buildup id=%d cost=%d lv=%d", num(bp:get_field("_Id")), num(bp:get_field("_Cost")), num(bp:get_field("_Lv"))))
        end
        if n > 0 then
            local bp = items:get_element(0):get_field("_BaseParam")
            for i = 1, 40 do
                trial(gen, i, "lotValueIndex c" .. c, function() return num(bp:call("lotValueIndex", SEED)) end)
            end
        end
    end

    w("== lotCustomBuildupIndex")
    local emptyIds = try(function() return ACD:get_method("getBuildupIdListByType"):call(acd, 0, 99) end)
    w("idList used = " .. list_str(emptyIds))
    for _, c in ipairs(cats) do
        for _, cc in ipairs({ cost, 6, 3 }) do
            for i = 1, 20 do
                trial(gen, i, string.format("lotCustomBuildupIndex c%d cost%d", c, cc), function()
                    return num(ACD:get_method("lotCustomBuildupIndex"):call(acd, c, cc, emptyIds, SEED))
                end)
            end
        end
    end

    w("== lotSkillId")
    for _, cc in ipairs({ 3, 6, 9, 12, 15, 18 }) do
        for i = 1, 40 do
            trial(gen, i, "lotSkillId cost" .. cc, function() return num(MOD:get_method("lotSkillId"):call(nil, cc, SEED)) end)
        end
    end

    w("== createResult (full)")
    for t = 0, 3 do
        for i = 1, 40 do
            trial(gen, i, string.format("createResult type%d", t), function()
                return result_str(ACD:get_method("createResult"):call(acd, cost, slotBlank, skills, true, t, SEED))
            end)
        end
    end

    tracing = false
    local bad = restore(snap)
    w(string.format("== restored %d generators, %d mismatches", #snap, bad))
    w("== passive (game calls)")
    for _, p in ipairs(passive) do w(p) end

    local f = io.open(OUT, "w")
    f:write(table.concat(L, "\n"), "\n")
    f:close()
    status = string.format("written: reframework/data/%s (%d lines, restore mismatches: %d)", OUT, #L, bad)
end

local function write_passive()
    local f = io.open("QuriousPassive.txt", "w")
    f:write(table.concat(passive, "\n"), "\n")
    f:close()
end

re.on_draw_ui(function()
    if imgui.tree_node("Qurious trace") then
        imgui.text(status)
        if imgui.button("Run trace") then
            local ok, err = pcall(run)
            tracing = false
            if not ok then status = "error: " .. tostring(err) end
        end
        imgui.text(string.format("game createResult calls logged: %d", #passive))
        if imgui.button("Write passive log") then pcall(write_passive) end
        imgui.tree_pop()
    end
end)

re.on_frame(function()
    if not hooks_installed and fdm() then pcall(install_hooks) end
end)
