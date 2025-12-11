-- --------------------------------------------------------
-- Function 1: Configure and Start the Measurement
-- --------------------------------------------------------
function StartVoltmeterBurst(count, verbose)
    -- Default to 20 readings if count is not provided
    if count == nil then count = 20 end
    if verbose == nil then verbose = true end

    -- Reset the SMU to default state
    smua.reset()
    
    -- 1. SPEED & RANGE OPTIMIZATION
    smua.measure.nplc = 0.001
    smua.measure.autozero = smua.AUTOZERO_OFF
    smua.measure.autorangev = smua.AUTORANGE_OFF
    smua.measure.rangev = 20
    smua.measure.delay = 0

    -- 2. VOLTMETER SOURCE CONFIGURATION (Source 0A)
    smua.source.func = smua.OUTPUT_DCAMPS
    smua.source.rangei = 100e-9 
    smua.source.leveli = 0
    smua.source.limitv = 40 

    -- 3. BUFFER & TRIGGER MODEL SETUP
    smua.nvbuffer1.clear()
    smua.nvbuffer1.appendmode = 1
    smua.nvbuffer1.collecttimestamps = 1 
    smua.trigger.measure.v(smua.nvbuffer1)

    smua.trigger.count = count
    
    -- FIXED: Disable Source Action. 
    -- We are not sweeping (changing) the source, so we must disable this 
    -- to prevent Error 5059. The Source will stay at the 0A level set above.
    smua.trigger.source.action = smua.DISABLE
    
    -- Enable Measure Action
    smua.trigger.measure.action = smua.ENABLE
    
    -- Set stimuli to Immediate (0) for fastest execution
    smua.trigger.arm.stimulus = 0
    smua.trigger.source.stimulus = 0 
    smua.trigger.measure.stimulus = 0 

    -- 4. START EXECUTION
    if verbose then
        print("Starting measurement burst of " .. count .. " readings...")
    end
    smua.source.output = smua.OUTPUT_ON
    
    -- This initiates the background process and returns immediately
    smua.trigger.initiate()
end

-- --------------------------------------------------------
-- Function 2: Retrieve Results
-- --------------------------------------------------------
function GetVoltmeterData(verbose)
    if verbose == nil then verbose = true end
    -- Turn off output when retrieving data
    smua.source.output = smua.OUTPUT_OFF

    if smua.nvbuffer1.n > 0 then
        if verbose then
            print(string.format("Retrieved %d measurements:", smua.nvbuffer1.n))
            printbuffer(1, smua.nvbuffer1.n, smua.nvbuffer1)
        end
    else
        print("Buffer is empty. Measurement might still be running or failed.")
    end
end