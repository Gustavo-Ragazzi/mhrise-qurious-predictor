-- Research probe #3: bulk createResult samples (REFramework autorun script).
--
-- Open Qurious Crafting at the smithy, pick an armor piece (augmentation enabled), then press
-- "Run bulk" in the "Qurious bulk" menu. For seeds 1..N it calls via.Random:init(seed) on one
-- generator, records the generator state, and calls ArmorCustomBuildupData.createResult for each of
-- the 4 augment types (from that same state). Work is spread over frames to keep the game
-- responsive. Every generator is restored afterwards. Do not save the game after testing.
--
-- Output: <game>/reframework/data/QuriousBulk.txt
--   header: armor name, table, cost, slots
--   lines:  <seed> <state hex> <type> <entries: category/id/value/skill/cost ...>

local OUT = "QuriousBulk.txt"
local SEED_GEN = 32
local status = "idle"
local job = nil

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
        p[#p + 1] = string.format("%08x", (obj:read_dword(off) or 0) & 0xffffffff)
    end
    return table.concat(p, "")
end

local function result_str(arr)
    if not arr then return "nil" end
    local parts = {}
    for i = 0, arr:get_size() - 1 do
        local r = arr:get_element(i)
        parts[#parts + 1] = string.format("%d/%d/%d/%d/%d", num(r:call("get_CategoryId")) or -1,
            num(r:call("get_Id")) or -1, num(r:call("get_Value")) or -1,
            num(r:call("get_PlSkillId")) or -1, num(r:call("get_Cost")) or -1)
    end
    return table.concat(parts, " ")
end

local function fdm() return sdk.get_managed_singleton("snow.data.FacilityDataManager") end

local function snapshot()
    local s = {}
    local m = fdm()
    for _, field in ipairs({ "_RandomManual", "_RandomAuto" }) do
        local arr = m:get_field(field)
        for i = 0, (arr and arr:get_size() or 0) - 1 do
            local g = arr:get_element(i)
            if g then s[#s + 1] = { obj = g, sid = g:call("get_StateId"), raw = raw(g) } end
        end
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

local function start(count)
    local smithy = sdk.get_managed_singleton("snow.gui.fsm.smithy.GuiSmithyFsmManager")
    local inv = smithy and smithy:call("get_CustomBuildupInventoryData")
    if not inv then status = "open Qurious Crafting and select an armor piece first" return end
    local armor = inv:call("getArmorData")
    local base = inv:call("getArmorBaseData")
    local tableNo = num(armor:call("get_CustomTableNo"))
    local cost = num(armor:call("get_CustomCost"))
    local slots = armor:call("getOriginalSlotLvTable")
    local s0, s1, s2 = num(slots:get_element(0)), num(slots:get_element(1)), num(slots:get_element(2))
    local f = io.open(OUT, "w")
    f:write(string.format("# armor=%s id=%s table=%d cost=%d slots=%d,%d,%d\n", tostring(armor:call("getName")),
        tostring(num(armor:call("get_Id"))), tableNo, cost, s0, s1, s2))
    job = {
        f = f, seed = 1, count = count, cost = cost, slotBlank = 12 - s0 - s1 - s2,
        skills = base:call("get_AllSkillDataList"),
        acd = sdk.get_managed_singleton("snow.data.CustomBuildupModule"):getArmorData(tableNo),
        method = sdk.find_type_definition("snow.data.ArmorCustomBuildupData"):get_method("createResult"),
        gen = fdm():get_field("_RandomManual"):get_element(SEED_GEN),
        snap = snapshot(),
    }
    status = "running…"
end

local function step()
    if not job then return end
    local stop = math.min(job.seed + 99, job.count)
    for seed = job.seed, stop do
        job.gen:call("init", seed)
        local sid = job.gen:call("get_StateId")
        local pre = raw(job.gen)
        for t = 0, 3 do
            job.gen:call("set_StateId", sid)
            local ok, res = pcall(function()
                return result_str(job.method:call(job.acd, job.cost, job.slotBlank, job.skills, true, t, SEED_GEN))
            end)
            job.f:write(string.format("%d %s %d %s\n", seed, pre, t, ok and res or ("ERR " .. tostring(res))))
        end
    end
    job.seed = stop + 1
    status = string.format("running… %d / %d seeds", stop, job.count)
    if job.seed > job.count then
        local bad = restore(job.snap)
        job.f:close()
        status = string.format("written: reframework/data/%s (%d seeds, restore mismatches: %d)", OUT, job.count, bad)
        job = nil
    end
end

re.on_frame(function()
    if job then
        local ok, err = pcall(step)
        if not ok then
            pcall(function() restore(job.snap); job.f:close() end)
            job = nil
            status = "error: " .. tostring(err)
        end
    end
end)

re.on_draw_ui(function()
    if imgui.tree_node("Qurious bulk") then
        imgui.text(status)
        if not job and imgui.button("Run bulk (20000 seeds x 4 types)") then
            local ok, err = pcall(start, 20000)
            if not ok then status = "error: " .. tostring(err) end
        end
        imgui.tree_pop()
    end
end)
