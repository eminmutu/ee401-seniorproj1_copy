-- This script configures the Keithley 2602B to:
-- 1. Wait for a trigger from the front panel (TRIG button).
-- 2. Measure the voltage using SMU A after the trigger.
-- 3. Display the measurement result on the front panel.
-- 4. Optionally beep to indicate the trigger was received.
-- 5. Ensure the output is turned off at the end.

-- Clear any previously detected command interface triggers.
trigger.clear()
-- Clear any previously detected display triggers.
display.trigger.clear()

-- Turn on output.
smua.source.output = smua.OUTPUT_ON

-- Prompt on the front panel and wait for TRIG (timeout 30 s).
display.clear()
display.setcursor(1, 1)
display.settext("Ready to measure")
display.setcursor(2, 1)
display.settext("Press TRIG (30 s)")
local triggered = display.trigger.wait(30)
display.clear()

-- Get a voltage reading after the display trigger (or timeout).
local reading = smua.measure.v()

-- Display the measurement result on the front panel
display.clear()
display.setcursor(1, 1)
display.settext("Measurement Result:")
display.setcursor(2, 1)
display.settext(string.format("V = %.6f", reading))

-- Ensure output is turned off at the end
smua.source.output = smua.OUTPUT_OFF

-- Optional status output.
print(string.format("display.trigger.wait -> %s; V = %.6f", tostring(triggered), reading))