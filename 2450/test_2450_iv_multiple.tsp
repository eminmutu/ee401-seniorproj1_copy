-- Linear voltage sweep that stores current readings in defbuffer1 and echoes the results.
-- Uses front-panel two-wire connections: source voltage, measure current.
function iv_sweep_linear(start_v, stop_v, step_v, ilimit, nplc, settle_s)
    if start_v == nil then start_v = -4 end
    if stop_v == nil then stop_v = 4 end
    if step_v == nil then step_v = 0.1 end
    if ilimit == nil then ilimit = 1 end
    if nplc == nil then nplc = 1 end
    if settle_s == nil then settle_s = 0.01 end
    if step_v == 0 then
        error("step_v must be non-zero")
    end

    -- Determine step direction so we terminate correctly.
    local direction = (step_v > 0) and 1 or -1
    if direction > 0 and start_v > stop_v then
        error("For positive step_v the stop_v must be >= start_v")
    elseif direction < 0 and start_v < stop_v then
        error("For negative step_v the stop_v must be <= start_v")
    end

    smu.reset()

    -- Measurement configuration: measure DC current using the front terminals.
    smu.measure.func = smu.FUNC_DC_CURRENT
    pcall(function() smu.measure.terminals = smu.TERMINALS_FRONT end)
    smu.measure.autorange = smu.ON
    smu.measure.nplc = nplc
    smu.measure.count = 1

    -- Source configuration: source DC voltage with compliance current.
    smu.source.func = smu.FUNC_DC_VOLTAGE
    pcall(function() smu.source.terminals = smu.TERMINALS_FRONT end)
    smu.source.ilimit.level = ilimit
    smu.source.highc = smu.OFF
    smu.source.delay = 0

    -- Prepare buffer to capture readings, timestamps, and source levels.
    defbuffer1.clear()
    defbuffer1.appendmode = 1
    pcall(function() defbuffer1.collecttimestamps = 1 end)
    pcall(function() defbuffer1.collectsourcevalues = 1 end)

    smu.source.output = smu.ON

    local point = 0
    local level = start_v
    local captured_levels = {}
    local epsilon = math.abs(step_v) * 1e-9 + 1e-12
    while (direction > 0 and level <= stop_v + epsilon) or (direction < 0 and level >= stop_v - epsilon) do
        smu.source.level = level
        delay(settle_s)
        smu.measure.read(defbuffer1)
        point = point + 1
        captured_levels[point] = level
        level = level + step_v
    end

    -- Return to 0 V and disable output before reporting results.
    smu.source.level = 0
    smu.source.output = smu.OFF

    print_buffer_iv(defbuffer1, captured_levels)

    return point
end

-- Quick helper to print a buffer containing an IV sweep.
function print_buffer_iv(buffer, fallback_sources)
    if buffer == nil then buffer = defbuffer1 end
    if buffer.n == 0 then
        print("Buffer is empty.")
        return
    end

    local function get_source_value(idx)
        local ok, value = pcall(function() return buffer.sourcevalues[idx] end)
        if ok and value ~= nil then
            return value
        elseif fallback_sources ~= nil then
            return fallback_sources[idx]
        else
            return nil
        end
    end

    local time_ok, time_val = pcall(function() return buffer.relativetimestamps[1] end)
    local has_time = time_ok and (time_val ~= nil)

    if has_time then
        print("Point", "Voltage (V)", "Current (A)", "Time (s)")
    else
        print("Point", "Voltage (V)", "Current (A)")
    end

    for i = 1, buffer.n do
        local v = get_source_value(i)
        local current = buffer[i]
        if has_time then
            local _, time_point = pcall(function() return buffer.relativetimestamps[i] end)
            print(i, v, current, time_point)
        else
            print(i, v, current)
        end
    end
end
