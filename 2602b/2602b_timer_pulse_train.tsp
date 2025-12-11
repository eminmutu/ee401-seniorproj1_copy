-- Helper functions for generating a voltage pulse train with SMUA.
-- This refactors the reference example to be callable from other code,
-- mirroring the structure used in timer_pulse_single.tsp.

-- still can't go lower than 50us, most probably a probing issue
-- it is also said that it can't go lower than 1us

local function configure_pulse_timers(period_timer_index, pulse_timer_index, pulse_period_s, pulse_width_s, pulse_count)
    local period_timer = trigger.timer[period_timer_index]
    period_timer.delay = pulse_period_s
    period_timer.count = math.max(pulse_count - 1, 0)
    period_timer.passthrough = true
    period_timer.stimulus = smua.trigger.ARMED_EVENT_ID

    local pulse_timer = trigger.timer[pulse_timer_index]
    pulse_timer.delay = pulse_width_s
    pulse_timer.count = 1
    pulse_timer.passthrough = false
    pulse_timer.stimulus = period_timer.EVENT_ID

    return period_timer, pulse_timer
end

function run_pulse_train(pulse_level, pulse_width_us, pulse_period_us, bias_level, current_limit, pulse_count, period_timer_index, pulse_timer_index)
    if pulse_level == nil then pulse_level = 5 end
    if pulse_width_us == nil then pulse_width_us = 100 end
    if pulse_period_us == nil then pulse_period_us = 500 end
    if bias_level == nil then bias_level = 0 end
    if current_limit == nil then current_limit = 0.1 end
    if pulse_count == nil then pulse_count = 10 end
    if period_timer_index == nil then period_timer_index = 1 end
    if pulse_timer_index == nil then pulse_timer_index = 2 end

    if pulse_count <= 0 then
        error("pulse_count must be greater than zero")
    end
    if pulse_width_us <= 0 then
        error("pulse_width_us must be greater than zero")
    end
    if pulse_period_us <= 0 then
        error("pulse_period_us must be greater than zero")
    end
    if pulse_period_us < pulse_width_us then
        error("pulse_period_us must be greater than or equal to pulse_width_us")
    end

    local pulse_width_s = pulse_width_us * 1e-6
    local pulse_period_s = pulse_period_us * 1e-6

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

    -- Configure the trigger-timer parameters to output the pulse train.
    local period_timer, pulse_timer = configure_pulse_timers(
        period_timer_index,
        pulse_timer_index,
        pulse_period_s,
        pulse_width_s,
        pulse_count
    )

    -- Configure the trigger model to execute a fixed-level voltage pulse list sweep.
    smua.trigger.source.listv({pulse_level})
    smua.trigger.source.action = smua.ENABLE
    smua.trigger.source.stimulus = period_timer.EVENT_ID

    -- Disable measurements to keep the pulse generation path as fast as possible.
    smua.trigger.measure.action = smua.DISABLE

    -- Set the trigger source limit and measurement range.
    smua.trigger.source.limiti = current_limit
    smua.measure.rangei = current_limit

    -- Configure the endpulse action to achieve individual pulses.
    smua.trigger.endpulse.action = smua.SOURCE_IDLE
    smua.trigger.endpulse.stimulus = pulse_timer.EVENT_ID

    -- Set the appropriate counts for the trigger model.
    smua.trigger.arm.count = 1
    smua.trigger.count = pulse_count

    -- Turn on the SMU output and initiate the trigger model to output the pulse train.
    smua.source.output = smua.OUTPUT_ON
    smua.trigger.initiate()

    -- Wait for the sweep to complete.
    waitcomplete()

    -- Turn off SMU output.
    smua.source.output = smua.OUTPUT_OFF

    print(string.format(
        "PULSE_TRAIN_DONE,level=%.6fV,width_us=%.3f,period_us=%.3f,count=%d,bias=%.6fV,limit=%.6fA",
        pulse_level,
        pulse_width_us,
        pulse_period_us,
        pulse_count,
        bias_level,
        current_limit))
end

-- Convenience wrapper that mirrors the reference example.
function run_default_pulse_train()
    run_pulse_train(5, 50, 100, 0, 0.1, 10, 1, 2)
end
