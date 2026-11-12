-- Research probe for the qurious crafting RNG (REFramework autorun script).
--
-- Phase 1: dumps type layouts (via.Random, FacilityDataManager, CustomBuildup*) and the live
-- state of every FacilityDataManager._RandomManual generator, then samples a few values from
-- two generators and RESTORES their state (same technique as the "Qurious Preview and Export
-- as csv" mod). Nothing is written to the save; still, do not save the game while testing.
--
-- Output: <game>/reframework/data/QuriousProbe.txt (written once per game session, after a
-- hunter is loaded). Press "Run again" in the REFramework menu to rewrite it.

local OUT = "QuriousProbe.txt"
local done = false
local status = "waiting for a loaded hunter"
local lines = {}

local function w(s) lines[#lines + 1] = s end

local function try(f, ...)
    local ok, r = pcall(f, ...)
    if ok then return r end
    return nil
end

local function tname(t)
    return t and try(function() return t:get_full_name() end) or "?"
end

-- Type layout dump ---------------------------------------------------------------------------

local dumped = {}
local queue = {}

local function interesting(name)
    return name and (name:find("Random") or name:find("CustomBuildup") or name:find("Buildup")
        or name == "snow.data.FacilityDataManager")
        and not name:find("^System%.") and not name:find("%[%]$")
end

local function enqueue(name)
    if interesting(name) and not dumped[name] then
        dumped[name] = true
        queue[#queue + 1] = name
    end
end

local function dump_type(name)
    local td = sdk.find_type_definition(name)
    if not td then
        w("TYPE " .. name .. " (not found)")
        return
    end
    w(string.format("TYPE %s size=%s valuetype=%s parent=%s", name,
        tostring(try(function() return td:get_size() end)),
        tostring(try(function() return td:is_value_type() end)),
        tname(try(function() return td:get_parent_type() end))))
    for _, f in ipairs(try(function() return td:get_fields() end) or {}) do
        local ft = tname(try(function() return f:get_type() end))
        w(string.format("  F %s : %s off=0x%x static=%s", f:get_name(), ft,
            try(function() return f:get_offset_from_base() end) or -1,
            tostring(try(function() return f:is_static() end))))
        enqueue(ft)
    end
    for _, m in ipairs(try(function() return td:get_methods() end) or {}) do
        local types = try(function() return m:get_param_types() end) or {}
        local names = try(function() return m:get_param_names() end) or {}
        local ps = {}
        for i, t in ipairs(types) do
            ps[#ps + 1] = tostring(names[i] or "?") .. ":" .. tname(t)
            enqueue(tname(t))
        end
        local rt = tname(try(function() return m:get_return_type() end))
        enqueue(rt)
        w(string.format("  M %s(%s) -> %s static=%s", m:get_name(), table.concat(ps, ", "), rt,
            tostring(try(function() return m:is_static() end))))
    end
end

local function dump_types()
    for _, n in ipairs({ "via.Random", "snow.data.FacilityDataManager", "snow.data.CustomBuildupModule" }) do
        enqueue(n)
    end
    local i = 1
    while i <= #queue and i <= 60 do
        dump_type(queue[i])
        i = i + 1
    end
end

-- Live generator state -----------------------------------------------------------------------

local function raw_state(obj)
    local parts = {}
    for off = 0x10, 0x3c, 4 do
        local v = try(function() return obj:read_dword(off) end)
        parts[#parts + 1] = v and string.format("%08x", v & 0xffffffff) or "????????"
    end
    return table.concat(parts, " ")
end

local function value_str(v)
    if v == nil then return "nil" end
    local t = type(v)
    if t == "number" or t == "boolean" or t == "string" then return tostring(v) end
    local s = try(function() return v:call("ToString()") end)
    return s and tostring(s) or tostring(v)
end

local function dump_manager_fields(fdm)
    local td = fdm:get_type_definition()
    for _, f in ipairs(td:get_fields()) do
        if not f:is_static() then
            local v = try(function() return fdm:get_field(f:get_name()) end)
            local size = v and type(v) ~= "number" and try(function() return v:get_size() end)
            if size then
                local items = {}
                for i = 0, math.min(size, 130) - 1 do
                    local e = try(function() return v:get_element(i) end)
                    items[#items + 1] = value_str(e)
                end
                w(string.format("  %s [%d] = %s", f:get_name(), size, table.concat(items, ", ")))
            else
                w(string.format("  %s = %s", f:get_name(), value_str(v)))
            end
        end
    end
end

-- Sampling -----------------------------------------------------------------------------------

-- Methods on via.Random that look like draws: no side effect besides advancing the state.
local function draw_methods()
    local td = sdk.find_type_definition("via.Random")
    local out = {}
    for _, m in ipairs(td and td:get_methods() or {}) do
        local n = m:get_name()
        local np = try(function() return m:get_num_params() end) or 99
        local static = try(function() return m:is_static() end)
        local rt = tname(try(function() return m:get_return_type() end))
        if not static and not n:find("^set_") and not n:find("^get_State") and n ~= "ToString"
            and n ~= "GetHashCode" and n ~= "Equals" and n ~= "GetType" and n ~= ".ctor"
            and rt ~= "System.Void" and (np == 0 or np == 2) then
            out[#out + 1] = { method = m, name = n, np = np, ret = rt }
        end
    end
    return out
end

local function sample(arr, index)
    local r = try(function() return arr:get_element(index) end)
    if not r then
        w(string.format("generator %d: missing", index))
        return
    end
    local sid = r:call("get_StateId")
    w(string.format("generator %d: StateId=%s raw=%s", index, value_str(sid), raw_state(r)))
    for _, d in ipairs(draw_methods()) do
        r:call("set_StateId", sid)
        local seq = {}
        for k = 1, 6 do
            local v
            if d.np == 0 then
                v = try(function() return d.method:call(r) end)
            else
                v = try(function() return d.method:call(r, 0, 100) end)
            end
            seq[#seq + 1] = string.format("%s{sid=%s raw=%s}", value_str(v),
                value_str(try(function() return r:call("get_StateId") end)), raw_state(r))
        end
        w(string.format("  %s/%d -> %s", d.name, d.np, table.concat(seq, " ; ")))
    end
    r:call("set_StateId", sid)
    w(string.format("  restored: StateId=%s raw=%s", value_str(r:call("get_StateId")), raw_state(r)))
end

-- Driver -------------------------------------------------------------------------------------

local function hunter_loaded()
    local pm = sdk.get_managed_singleton("snow.player.PlayerManager")
    return pm and try(function() return pm:call("findMasterPlayer") end) ~= nil
end

local function run()
    lines = {}
    dumped, queue = {}, {}
    w("== types")
    dump_types()
    local fdm = sdk.get_managed_singleton("snow.data.FacilityDataManager")
    if not fdm then
        w("FacilityDataManager singleton missing")
    else
        w("== FacilityDataManager fields")
        dump_manager_fields(fdm)
        local arr = fdm:get_field("_RandomManual")
        local n = arr and arr:get_size() or 0
        w(string.format("== _RandomManual (%d generators)", n))
        for i = 0, n - 1 do
            local r = arr:get_element(i)
            w(string.format("  [%d] StateId=%s raw=%s", i,
                value_str(r and try(function() return r:call("get_StateId") end)), r and raw_state(r) or "-"))
        end
        w("== sampling (state restored after each method)")
        sample(arr, 32)
        sample(arr, 18)
    end
    local f = io.open(OUT, "w")
    if f then
        f:write(table.concat(lines, "\n"), "\n")
        f:close()
        status = "written: reframework/data/" .. OUT .. " (" .. #lines .. " lines)"
    else
        status = "cannot write " .. OUT
    end
end

re.on_frame(function()
    if not done and hunter_loaded() then
        done = true
        local ok, err = pcall(run)
        if not ok then status = "error: " .. tostring(err) end
    end
end)

re.on_draw_ui(function()
    if imgui.tree_node("Qurious RNG probe") then
        imgui.text(status)
        if imgui.button("Run again") then
            local ok, err = pcall(run)
            if not ok then status = "error: " .. tostring(err) end
        end
        imgui.tree_pop()
    end
end)
