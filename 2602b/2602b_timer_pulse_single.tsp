-- Helper functions for generating a single voltage pulse with SMUA.
-- This refactors the example script into callable routines so it can be
-- triggered from other code (similar to test_iv_multiple.tsp).

-- Example call from the terminal:
-- run_single_pulse(5, 20, 0, 0.05, 1)

local function configure_pulse_timer(timer_index, pulse_width_s)
    local timer = trigger.timer[timer_index]
    timer.delay = pulse_width_s
    timer.count = 1
    timer.passthrough = false
    timer.stimulus = smua.trigger.ARMED_EVENT_ID
end

function run_single_pulse(pulse_level, pulse_width_us, bias_level, current_limit, timer_index)
    if pulse_level == nil then pulse_level = 5 end
    if pulse_width_us == nil then pulse_width_us = 500 end
    if bias_level == nil then bias_level = 0 end
    if current_limit == nil then current_limit = 0.1 end
    if timer_index == nil then timer_index = 1 end

    if pulse_width_us <= 0 then
        error("pulse_width_us must be greater than zero")
    end

    local pulse_width_s = pulse_width_us * 1e-6

    -- Reset SourceMeter instrument to default conditions.
    if reset then
        reset()
    else
        smua.reset()
    end

    -- Configure the source function.
    smua.source.func = smua.OUTPUT_DCVOLTS

    -- Set the voltage source range and the idle (bias) source level and limit.
    local source_range = math.max(math.abs(bias_level), math.abs(pulse_level))
    if source_range == 0 then
        source_range = 0.2
    end
    smua.source.rangev = source_range
    smua.source.levelv = bias_level
    smua.source.limiti = current_limit

    -- Configure the trigger-timer parameters to output a single pulse.
    configure_pulse_timer(timer_index, pulse_width_s)

    -- Configure the trigger model to execute a single-point voltage pulse list sweep.
    smua.trigger.source.listv({pulse_level})
    smua.trigger.source.action = smua.ENABLE
    smua.trigger.source.stimulus = 0

    -- Disable measurements to keep the pulse generation path as fast as possible.
    smua.trigger.measure.action = smua.DISABLE

    -- Set the trigger source limit and measurement range.
    smua.trigger.source.limiti = current_limit
    smua.measure.rangei = current_limit

    -- Configure the endpulse action to achieve a pulse.
    local timer = trigger.timer[timer_index]
    smua.trigger.endpulse.action = smua.SOURCE_IDLE
    smua.trigger.endpulse.stimulus = timer.EVENT_ID

    -- Set the appropriate counts for the trigger model.
    smua.trigger.arm.count = 1
    smua.trigger.count = 1

    -- Turn on the SMU output and initiate the trigger model to output a single pulse.
    smua.source.output = smua.OUTPUT_ON
    smua.trigger.initiate()

    -- Wait for the sweep to complete.
    waitcomplete()

    -- Turn off SMU output.
    smua.source.output = smua.OUTPUT_OFF

    print(string.format(
        "PULSE_DONE,level=%.6fV,width_us=%.3f,bias=%.6fV,limit=%.6fA",
        pulse_level, pulse_width_us, bias_level, current_limit))
end

-- Convenience wrapper that can be executed from the console to verify a fast pulse.
function run_fast_current_pulse()
    run_single_pulse(5, 20, 0, 0.05, 1)
end
