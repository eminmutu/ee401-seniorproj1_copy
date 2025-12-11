-- --------------------------------------------------------
-- Function 1: Configure and Start the Current Measurement
-- --------------------------------------------------------
function StartAmmeterBurst(count, verbose)
	if count == nil then count = 20 end
	if verbose == nil then verbose = true end

	smua.reset()

	-- Speed and range settings tailored for current capture
	smua.measure.nplc = 0.001
	smua.measure.autozero = smua.AUTOZERO_OFF
	smua.measure.autorangei = smua.AUTORANGE_OFF
	smua.measure.rangei = 100e-3
	smua.measure.delay = 0

	-- Source zero volts so the SMU behaves as an ammeter
	smua.source.func = smua.OUTPUT_DCVOLTS
	smua.source.rangev = 20
	smua.source.levelv = 0
	smua.source.limiti = 1

	-- Buffer and trigger configuration for current readings
	smua.nvbuffer1.clear()
	smua.nvbuffer1.appendmode = 1
	smua.nvbuffer1.collecttimestamps = 1
	smua.trigger.measure.i(smua.nvbuffer1)

	smua.trigger.count = count
	smua.trigger.source.action = smua.DISABLE
	smua.trigger.measure.action = smua.ENABLE
	smua.trigger.arm.stimulus = 0
	smua.trigger.source.stimulus = 0
	smua.trigger.measure.stimulus = 0

	if verbose then
		print("Starting ammeter burst of " .. count .. " readings...")
	end

	smua.source.output = smua.OUTPUT_ON
	smua.trigger.initiate()
end

-- --------------------------------------------------------
-- Function 2: Retrieve Current Results
-- --------------------------------------------------------
function GetAmmeterData(verbose)
	if verbose == nil then verbose = true end
	smua.source.output = smua.OUTPUT_OFF

	if smua.nvbuffer1.n > 0 then
		if verbose then
			print(string.format("Retrieved %d current measurements:", smua.nvbuffer1.n))
			printbuffer(1, smua.nvbuffer1.n, smua.nvbuffer1)
		end
	else
		print("Buffer is empty. Measurement might still be running or failed.")
	end
end
