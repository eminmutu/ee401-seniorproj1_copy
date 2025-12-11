-- Keithley 2602B Beep Script
-- This script makes the instrument beep using the beeper.beep() function.

-- Configure the beep parameters (frequency in Hz, duration in seconds)
local frequency = 2400  -- Adjusted frequency to 2400 Hz (safe range)
local duration = 1      -- Adjusted duration to 2 seconds (safe range)

-- Enable the beeper
beeper.enable = beeper.ON

-- Trigger the beep with the specified parameters
beeper.beep(duration, frequency)

-- Print confirmation to the instrument's display
print("Beep triggered: Duration = " .. duration .. " s, Frequency = " .. frequency .. " Hz")
