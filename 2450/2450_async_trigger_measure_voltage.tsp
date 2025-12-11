function configure_voltmeter(range, nplc)
    local range_val = range or 2
    local nplc_val = nplc or 0.01

    smu.reset()

    -- 1. SETUP SOURCE (Source 0A)
    smu.source.func = smu.FUNC_DC_CURRENT
    
    -- CRITICAL FIX: Turn Auto-Range OFF *before* setting the Range
    smu.source.autorange = smu.OFF            
    smu.source.level = 0
    smu.source.readback = smu.ON

    -- 2. SETUP MEASURE
    smu.measure.func = smu.FUNC_DC_VOLTAGE
    
    -- CRITICAL FIX: Turn Auto-Range OFF *before* setting the Range
    smu.measure.autorange = smu.OFF  
    smu.measure.range = range_val    
    
    smu.measure.nplc = nplc_val
    smu.measure.sense = smu.SENSE_4WIRE
    pcall(function() smu.measure.terminals = smu.TERMINALS_FRONT end)
    pcall(function() smu.source.terminals = smu.TERMINALS_FRONT end)

    -- 3. ACTIVATE
    smu.source.output = smu.ON
end

-- Capture `count` voltage readings automatically, spacing each measurement by
-- `interval_s` seconds (0 -> back-to-back as fast as possible).
function auto_triggered_voltage_measurements(count, interval_s)
    local target = math.max(1, math.floor(count or 1))
    local spacing = math.max(interval_s or 0, 0)

    defbuffer1.clear()
    defbuffer1.appendmode = 1

    display.clear()
    display.settext(display.TEXT1, string.format("Auto %d @ %.3fs", target, spacing))

    for idx = 1, target do
        if spacing > 0 and idx > 1 then
            delay(spacing)
        end
        local reading = smu.measure.read(defbuffer1)
        print(string.format("Auto %d -> %.9f V", idx, reading))
        display.settext(display.TEXT2, string.format("Last #%d: %.6f V", idx, reading))
    end

    display.settext(display.TEXT1, string.format("Auto done %d", defbuffer1.n))
    display.settext(display.TEXT2, "")

    return defbuffer1.n
end

-- Example usage:
-- configure_voltmeter(2, 0.01)
-- auto_triggered_voltage_measurements(50, 0.05)