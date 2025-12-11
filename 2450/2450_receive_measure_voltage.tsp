local DEFAULT_EDGE = "falling"
local DEFAULT_LINE = 1
local DEFAULT_MODE = "trigger_in"
local EDGE_MAP = {
    rising = trigger.EDGE_RISING,
    falling = trigger.EDGE_FALLING,
    either = trigger.EDGE_EITHER
}
local MODE_MAP = {
    digital_in = digio.MODE_DIGITAL_IN,
    digital_out = digio.MODE_DIGITAL_OUT,
    digital_open_drain = digio.MODE_DIGITAL_OPEN_DRAIN,
    trigger_in = digio.MODE_TRIGGER_IN,
    trigger_out = digio.MODE_TRIGGER_OUT,
    trigger_open_drain = digio.MODE_TRIGGER_OPEN_DRAIN,
    synchronous_master = digio.MODE_SYNCHRONOUS_MASTER,
    synchronous_acceptor = digio.MODE_SYNCHRONOUS_ACCEPTOR
}

local receive_measure_cancel_flag = false

function receive_measure_cancel()
    receive_measure_cancel_flag = true
end

local function resolve_edge(edge_name)
    if edge_name == nil then
        return EDGE_MAP[DEFAULT_EDGE], DEFAULT_EDGE
    end
    local key = string.lower(tostring(edge_name))
    local value = EDGE_MAP[key]
    if value == nil then
        return EDGE_MAP[DEFAULT_EDGE], DEFAULT_EDGE
    end
    return value, key
end

local function normalize_mode(mode_name)
    if mode_name == nil then
        return DEFAULT_MODE
    end
    local key = string.lower(tostring(mode_name))
    key = string.gsub(key, "%s+", "_")
    return key
end

local function resolve_mode(mode_name)
    local key = normalize_mode(mode_name)
    local value = MODE_MAP[key]
    if value == nil then
        return MODE_MAP[DEFAULT_MODE], DEFAULT_MODE
    end
    return value, key
end

local function resolve_line(line_number)
    local idx = tonumber(line_number)
    if idx == nil then
        idx = DEFAULT_LINE
    end
    if idx < 1 then
        idx = 1
    elseif idx > 6 then
        idx = 6
    end
    return math.floor(idx + 0.0001)
end

local function configure_meter(range_value, nplc_value)
    local range_val = tonumber(range_value) or 2
    local nplc_val = tonumber(nplc_value) or 0.01

    smu.reset()

    smu.source.func = smu.FUNC_DC_CURRENT
    smu.source.autorange = smu.OFF
    smu.source.level = 0
    smu.source.readback = smu.ON

    smu.measure.func = smu.FUNC_DC_VOLTAGE
    smu.measure.autorange = smu.OFF
    smu.measure.range = range_val
    smu.measure.nplc = nplc_val
    smu.measure.sense = smu.SENSE_4WIRE
    pcall(function() smu.measure.terminals = smu.TERMINALS_FRONT end)
    pcall(function() smu.source.terminals = smu.TERMINALS_FRONT end)

    smu.source.output = smu.ON
end

local function ensure_line(line_number, edge, mode_value)
    digio.line[line_number].mode = mode_value
    if mode_value == digio.MODE_TRIGGER_IN or mode_value == digio.MODE_TRIGGER_OPEN_DRAIN then
        trigger.digin[line_number].edge = edge
        trigger.digin[line_number].clear()
    end
end

local function wait_for_trigger(line_number, timeout,
                                edge, mode_value, edge_label, mode_label)
    local chunk = 0.1
    local elapsed = 0
    local triggered = false

    display.changescreen(display.SCREEN_USER_SWIPE)
    display.settext(display.TEXT1, "Waiting for trigger")
    display.settext(display.TEXT2,
        string.format("DIGIO%d (%s, %s)", line_number, edge_label, mode_label))

    while not triggered and not receive_measure_cancel_flag do
        local wait_time = chunk
        if timeout ~= nil then
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
        triggered = trigger.digin[line_number].wait(wait_time)
        if timeout ~= nil then
            elapsed = elapsed + wait_time
        end
    end

    if receive_measure_cancel_flag then
        display.settext(display.TEXT1, "Cancelled")
        display.settext(display.TEXT2, "")
        return "CANCEL"
    end

    if triggered then
        display.settext(display.TEXT1, "Trigger detected")
        display.settext(display.TEXT2, "Measuring...")
        return "TRIGGER"
    end

    display.settext(display.TEXT1, "Trigger timeout")
    display.settext(display.TEXT2, "")
    return "TIMEOUT"
end

function wait_for_trigger_measure(count, interval_s, range_value, nplc_value,
                                  timeout_s, edge_name, line_number, mode_name)
    local samples = math.max(1, math.floor(tonumber(count) or 1))
    local spacing = math.max(tonumber(interval_s) or 0, 0)
    local timeout = tonumber(timeout_s)

    local edge, edge_label = resolve_edge(edge_name)
    local mode_value, mode_label = resolve_mode(mode_name)
    local line = resolve_line(line_number)

    receive_measure_cancel_flag = false
    configure_meter(range_value, nplc_value)
    ensure_line(line, edge, mode_value)

    if mode_value ~= digio.MODE_TRIGGER_IN and mode_value ~= digio.MODE_TRIGGER_OPEN_DRAIN then
        display.settext(display.TEXT1, "Mode not trigger input")
        display.settext(display.TEXT2, mode_label)
        return "INVALID_MODE"
    end

    local wait_status = wait_for_trigger(line, timeout, edge, mode_value, edge_label, mode_label)
    if wait_status ~= "TRIGGER" then
        return wait_status
    end

    defbuffer1.clear()
    defbuffer1.appendmode = 1

    for idx = 1, samples do
        if receive_measure_cancel_flag then
            display.settext(display.TEXT1, "Capture cancelled")
            display.settext(display.TEXT2, string.format("Stored %d", defbuffer1.n))
            return "CANCEL"
        end
        if spacing > 0 and idx > 1 then
            delay(spacing)
        end
        local reading = smu.measure.read(defbuffer1)
        print(string.format("Sample %d: %.9f V", idx, reading))
    end

    display.settext(display.TEXT1, string.format("Captured %d", defbuffer1.n))
    display.settext(display.TEXT2, "")
    return defbuffer1.n
end
