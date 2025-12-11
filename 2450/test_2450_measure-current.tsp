-- Configure the 2450 SourceMeter as a low-impedance current meter while keeping the output on.

DEFAULT_SAMPLES = 10
DEFAULT_NPLC = 0.01

function configure_ammeter(range, nplc)
    local nplc_value = nplc or DEFAULT_NPLC

    reset()

    smu.source.func = smu.FUNC_DC_VOLTAGE
    smu.source.level = 0
    smu.source.autorange = smu.ON
    smu.source.readback = smu.ON
    smu.source.offmode = smu.OFFMODE_ZERO

    smu.measure.func = smu.FUNC_DC_CURRENT
    smu.measure.terminals = smu.TERMINALS_FRONT
    smu.measure.sense = smu.SENSE_4WIRE
    smu.measure.nplc = nplc_value
    smu.source.ilimit.level = 0.5
    if range ~= nil then
        smu.measure.autorange = smu.OFF
        smu.measure.range = range
    else
        smu.measure.autorange = smu.ON
    end

    smu.source.output = smu.ON
end

function acquire_current_samples(samples)
    local requested = samples or DEFAULT_SAMPLES
    if requested < 1 then requested = 1 end

    if requested > defbuffer1.capacity then
        print(string.format("Requested %d samples; truncating to defbuffer1 capacity %d.",
            requested, defbuffer1.capacity))
        requested = defbuffer1.capacity
    end

    defbuffer1.clear()
    defbuffer1.appendmode = 1

    for _ = 1, requested do
        smu.measure.read(defbuffer1)
    end

    local total = 0
    for i = 1, defbuffer1.n do
        total = total + defbuffer1[i]
    end

    local mean = defbuffer1.n > 0 and (total / defbuffer1.n) or 0
    return mean, defbuffer1.n
end

function measure_current(samples, range, nplc)
    configure_ammeter(range, nplc)
    return acquire_current_samples(samples)
end

function print_current(samples, range, nplc)
    local current, points = measure_current(samples, range, nplc)
    print(string.format("Current: %.6e A (samples: %d)", current, points))
    return current, points
end

function print_current_buffer(buffer)
    if buffer == nil then buffer = defbuffer1 end
    if buffer.n == 0 then
        print("Buffer is empty.")
        return
    end

    print("Point", "Current (A)")
    for i = 1, buffer.n do
        print(i, buffer[i])
    end
end

function ammeter_run(samples, range, nplc)
    local current, points = measure_current(samples, range, nplc)
    print(string.format("Ammeter run complete: %.6e A (samples: %d)", current, points))
    print_current_buffer(defbuffer1)
    ammeter_output_off()
    return current, points
end

function ammeter_output_off()
    smu.source.output = smu.OFF
end
