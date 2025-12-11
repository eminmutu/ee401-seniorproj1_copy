DEFAULT_EDGE = "rising"    -- change to "rising"/"either" if needed
DEFAULT_LINE = 1

EDGE_MAP = {
    rising  = trigger.EDGE_RISING,
    falling = trigger.EDGE_FALLING,
    either  = trigger.EDGE_EITHER
}

function _resolve_edge(edge_name)
    if edge_name == nil then
        return EDGE_MAP[DEFAULT_EDGE], DEFAULT_EDGE
    end
    local key = string.lower(tostring(edge_name))
    local val = EDGE_MAP[key]
    if val == nil then
        return EDGE_MAP[DEFAULT_EDGE], DEFAULT_EDGE
    end
    return val, key
end

function _resolve_line(line_number)
    local idx = tonumber(line_number)
    if idx == nil then idx = DEFAULT_LINE end
    if idx < 1 then idx = 1 elseif idx > 6 then idx = 6 end
    return math.floor(idx + 0.0001)
end

function _configure_meter(range_value)
    local range_val = tonumber(range_value) or 2

    -- Ensure the source function is compatible with measuring voltage.
    -- The 2450 cannot source and measure the same function simultaneously, so
    -- switch to sourcing current (0 A) when necessary to avoid conflicts.
    pcall(function()
        if smu.source.func ~= smu.FUNC_DC_CURRENT then
            smu.source.func = smu.FUNC_DC_CURRENT
        end
        smu.source.autorange = smu.ON
        smu.source.level = 0
        smu.source.readback = smu.ON
    end)

    -- Configure only measurement path for speed and safety
    smu.measure.func      = smu.FUNC_DC_VOLTAGE
    smu.measure.autorange = smu.OFF
    smu.measure.range     = range_val
    smu.measure.nplc      = 0.01

    -- Prefer front terminals if supported
    pcall(function() smu.measure.terminals = smu.TERMINALS_FRONT end)
end

function _configure_trigger(line_number, edge_name)
    local line = _resolve_line(line_number)
    local edge, edge_label = _resolve_edge(edge_name)

    digio.line[line].mode    = digio.MODE_TRIGGER_IN
    trigger.digin[line].edge = edge
    trigger.digin[line].clear()

    return line, edge_label
end

-- Public function: waits on DIGIO line and measures exactly at trigger using
-- the hardware digital-input wait (no trigger model to avoid read-only issues).
-- Args:
--   range_value (V) [optional] default 2
--   edge_name "rising"/"falling"/"either" [optional] default DEFAULT_EDGE
--   line_number 1..6 [optional] default 1
-- Returns:
--   reading value (number) or nil; also prints and displays result.
function triggered_measure_once(range_value, edge_name, line_number, timeout_s)
    _configure_meter(range_value)
    local line, edge_label = _configure_trigger(line_number, edge_name)

    display.changescreen(display.SCREEN_USER_SWIPE)
    display.settext(display.TEXT1, "Waiting trigger")
    display.settext(display.TEXT2, string.format("DIGIO%d (%s, NPLC 0.01)", line, edge_label))

    defbuffer1.clear()
    defbuffer1.appendmode = 1

    -- Wait in small chunks; returns immediately on actual edge
    local chunk = 0.25
    local got = false
    local elapsed = 0
    local has_timeout = (timeout_s ~= nil)
    local timeout = tonumber(timeout_s)

    while not got do
        local wait_time = chunk
        if has_timeout and timeout ~= nil then
            if elapsed >= timeout then
                break
            end
            if elapsed + wait_time > timeout then
                wait_time = timeout - elapsed
            end
        end
        if wait_time <= 0 then
            break
        end
        got = trigger.digin[line].wait(wait_time)
        if has_timeout and timeout ~= nil then
            elapsed = elapsed + wait_time
        end
    end

    if got then
        local v = smu.measure.read(defbuffer1)
        display.settext(display.TEXT1, "Triggered V")
        display.settext(display.TEXT2, string.format("%.9f V", v))
        print(string.format("$MEAS:DONE$ %.9f", v))
        return v
    else
        display.settext(display.TEXT1, "No trigger (timeout)")
        display.settext(display.TEXT2, "")
        print("$MEAS:TIMEOUT$")
        return nil
    end
end

-- Optional: diagnostic helper to see which settings fail on this unit
function triggered_measure_diag()
    local function try(label, fn)
        local ok, err = pcall(fn)
        if ok then
            print(label .. ": OK")
        else
            print(label .. ": " .. tostring(err))
        end
    end
    try("measure.func", function() smu.measure.func = smu.FUNC_DC_VOLTAGE end)
    try("measure.autorange OFF", function() smu.measure.autorange = smu.OFF end)
    try("measure.range 2V", function() smu.measure.range = 2 end)
    try("measure.nplc 0.01", function() smu.measure.nplc = 0.01 end)
    try("measure.autozero OFF", function() smu.measure.autozero = smu.AUTOZERO_OFF end)
    try("measure.terminals FRONT", function() smu.measure.terminals = smu.TERMINALS_FRONT end)
    try("digio.mode TRIGGER_IN", function() digio.line[1].mode = digio.MODE_TRIGGER_IN end)
    try("digin.edge FALLING", function() trigger.digin[1].edge = trigger.EDGE_FALLING end)
    try("digin.clear", function() trigger.digin[1].clear() end)
end