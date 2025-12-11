local DEFAULT_DIGIO_LINE = 9
local DEFAULT_EDGE = "rising"
local DEFAULT_TIMEOUT = 10
local DEFAULT_PULSEWIDTH = 10e-6

local EDGE_MODES = {
    rising  = digio.TRIG_RISINGA,
    falling = digio.TRIG_FALLINGA,
    either  = digio.TRIG_EITHER
}

local function resolve_line(line_number)
    local idx = tonumber(line_number) or DEFAULT_DIGIO_LINE
    if idx < 1 then
        idx = 1
    elseif idx > 14 then
        idx = 14
    end
    return math.floor(idx)
end

local function resolve_edge(edge_name)
    local key = string.lower(tostring(edge_name or DEFAULT_EDGE))
    return EDGE_MODES[key] or EDGE_MODES[DEFAULT_EDGE]
end

local function configure_digio_input(line_number, edge_mode, pulsewidth)
    local trig = digio.trigger[line_number]
    trig.mode = edge_mode
    trig.pulsewidth = pulsewidth or DEFAULT_PULSEWIDTH
    trig.clear()
    return trig
end

function wait_for_digio_trigger(line_number, timeout_seconds, edge_name)
    local line = resolve_line(line_number)
    local mode = resolve_edge(edge_name)
    local timeout = tonumber(timeout_seconds) or DEFAULT_TIMEOUT

    configure_digio_input(line, mode, DEFAULT_PULSEWIDTH)
    print(string.format("Waiting for %s edge on DIGIO %d (timeout %.3f s)...", edge_name or DEFAULT_EDGE, line, timeout))

    local detected = digio.trigger[line].wait(timeout)
    if detected then
        print("I got the trigger!")
    else
        print(string.format("Timed out: No trigger received within %.3f seconds.", timeout))
    end

    return detected
end

function run_receive_trigger(line_number, timeout_seconds, edge_name)
    smua.reset()
    return wait_for_digio_trigger(line_number, timeout_seconds, edge_name)
end