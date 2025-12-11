-- Configure the 2450 SourceMeter as a 4-wire voltmeter and keep the output on
-- so you can gather readings just like the front-panel Voltmeter quickset.

DEFAULT_SAMPLES = 10
DEFAULT_NPLC = 0.01

function configure_voltmeter(range, nplc)
    local nplc_value = nplc or DEFAULT_NPLC

    reset()

    smu.source.func = smu.FUNC_DC_CURRENT
    smu.source.level = 0
    smu.source.autorange = smu.OFF
    smu.source.readback = smu.ON
    smu.source.offmode = smu.OFFMODE_NORMAL

    smu.measure.func = smu.FUNC_DC_VOLTAGE
    smu.measure.terminals = smu.TERMINALS_FRONT
    smu.measure.sense = smu.SENSE_4WIRE
    smu.measure.autorange = smu.OFF
    smu.measure.nplc = nplc_value
    if range ~= nil then
        smu.measure.range = range
    end

    smu.source.output = smu.ON
end

function acquire_voltage_samples(samples)
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

function measure_voltage(samples, range, nplc)
    configure_voltmeter(range, nplc)
    return acquire_voltage_samples(samples)
end

function print_voltage(samples, range, nplc)
    local voltage, points = measure_voltage(samples, range, nplc)
    print(string.format("Voltage: %.6f V (samples: %d)", voltage, points))
    return voltage, points
end

function print_voltage_buffer(buffer)
    if buffer == nil then buffer = defbuffer1 end
    if buffer.n == 0 then
        print("Buffer is empty.")
        return
    end

    print("Point", "Voltage (V)")
    for i = 1, buffer.n do
        print(i, buffer[i])
    end
end

function voltmeter_run(samples, range, nplc)
    local voltage, points = measure_voltage(samples, range, nplc)
    print(string.format("Voltmeter run complete: %.6f V (samples: %d)", voltage, points))
    print_voltage_buffer(defbuffer1)
    voltmeter_output_off()
    return voltage, points
end

function voltmeter_output_off()
    smu.source.output = smu.OFF
end
