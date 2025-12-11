local DEFAULT_MEASURE_COUNT = 20
local DEFAULT_SOURCE_VOLTAGE = 0
local DEFAULT_SOURCE_RANGE = 2
local DEFAULT_COMPLIANCE_CURRENT = 10e-3
local DEFAULT_MEASURE_RANGE = 10e-3
local DEFAULT_NPLC = 0.01
local DEFAULT_BUFFER_CAPACITY = 2000
local DEFAULT_TRIG_LINE = 1
local DEFAULT_TRIG_EDGE = trigger.EDGE_RISING

local EDGE_MAP = {
	rising  = trigger.EDGE_RISING,
	falling = trigger.EDGE_FALLING,
	either  = trigger.EDGE_EITHER
}

local DIGIO_EVENTS = {
	[1] = trigger.EVENT_DIGIO1,
	[2] = trigger.EVENT_DIGIO2,
	[3] = trigger.EVENT_DIGIO3,
	[4] = trigger.EVENT_DIGIO4,
	[5] = trigger.EVENT_DIGIO5,
	[6] = trigger.EVENT_DIGIO6
}

function run_fast_external_trigger_timed(
	measure_count,
	source_current,
	source_range,
	measure_range,
	trig_line,
	trig_edge_name,
	nplc_value
)
	local t0 = localnode.gettime()

	local count = math.max(1, math.floor(tonumber(measure_count) or DEFAULT_MEASURE_COUNT))
	local compliance = math.abs(tonumber(source_current) or DEFAULT_COMPLIANCE_CURRENT)
	local src_range = tonumber(source_range) or DEFAULT_SOURCE_RANGE
	if src_range <= 0 or src_range < 1e-2 then
		src_range = DEFAULT_SOURCE_RANGE
	end
	local meas_range = tonumber(measure_range) or DEFAULT_MEASURE_RANGE
	local nplc = tonumber(nplc_value) or DEFAULT_NPLC
	if nplc <= 0 then
		nplc = DEFAULT_NPLC
	end

	local t_line = tonumber(trig_line) or DEFAULT_TRIG_LINE
	if t_line < 1 then
		t_line = 1
	elseif t_line > 6 then
		t_line = 6
	end

	local edge_key = string.lower(tostring(trig_edge_name or "rising"))
	local t_edge = EDGE_MAP[edge_key] or DEFAULT_TRIG_EDGE

	reset()
	errorqueue.clear()
	local fastBuf = buffer.make(math.max(DEFAULT_BUFFER_CAPACITY, count), buffer.STYLE_COMPACT)
	fastBuf.clear()

	local t_setup_done = localnode.gettime()
	local t_config_done = 0
	local t_trigger_armed = 0
	local t_finished = 0

	local ok, err = pcall(function()
		digio.line[t_line].mode = digio.MODE_TRIGGER_IN
		trigger.digin[t_line].edge = t_edge
		trigger.digin[t_line].clear()
		smu.source.func = smu.FUNC_DC_VOLTAGE
		smu.source.range = src_range
		smu.source.level = DEFAULT_SOURCE_VOLTAGE
		-- Compliance current is left at the instrument default for voltage sourcing to avoid read-only limits

		smu.measure.func = smu.FUNC_DC_CURRENT
		smu.measure.range = meas_range
		smu.measure.nplc = nplc
		smu.measure.autozero.enable = smu.OFF

		smu.source.output = smu.ON

		t_config_done = localnode.gettime()

		trigger.model.setblock(1, trigger.BLOCK_BUFFER_CLEAR, fastBuf)
		local event_obj = DIGIO_EVENTS[t_line]
		trigger.model.setblock(2, trigger.BLOCK_WAIT, event_obj)
		trigger.model.setblock(3, trigger.BLOCK_DELAY_CONSTANT, 0)
		trigger.model.setblock(4, trigger.BLOCK_MEASURE, fastBuf, count)
		trigger.model.setblock(5, trigger.BLOCK_NOP)

		trigger.model.initiate()
		t_trigger_armed = localnode.gettime()
		waitcomplete()
		t_finished = localnode.gettime()

		smu.source.output = smu.OFF
	end)

	if not ok then
		smu.source.output = smu.OFF
		print("Lua Error: " .. tostring(err))
		return nil
	end

	print("\n--- TIMING REPORT (Seconds) ---")
	print(string.format("1. Lua Setup Overhead:      %.5f s", t_setup_done - t0))
	print(string.format("2. Hardware Config (Relays):%.5f s", t_config_done - t_setup_done))
	print(string.format("3. Trigger Model Build:     %.5f s", t_trigger_armed - t_config_done))
	print(string.format("4. Wait Trigger + Burst:    %.5f s", t_finished - t_trigger_armed))
	print("-------------------------------")

	print("Reading Index", "Current (A)")
	for i = 1, fastBuf.n do
		print(i, fastBuf[i])
	end

	return fastBuf
end

function run_fast_external_trigger(
	measure_count,
	source_current,
	source_range,
	measure_range,
	trig_line,
	trig_edge_name,
	nplc_value
)
	return run_fast_external_trigger_timed(
		measure_count,
		source_current,
		source_range,
		measure_range,
		trig_line,
		trig_edge_name,
		nplc_value
	)
end
