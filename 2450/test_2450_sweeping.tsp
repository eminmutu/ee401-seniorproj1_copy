-- Reset the Model 2460 and clear the buffer.
reset()
-- Set the source and measure functions.
smu.source.func = smu.FUNC_DC_VOLTAGE
smu.measure.func = smu.FUNC_DC_CURRENT
-- Configure the measurement settings.
smu.measure.terminals = smu.TERMINALS_FRONT
-- smu.measure.sense = smu.SENSE_LOCAL
smu.measure.autorange = smu.ON
smu.measure.nplc = 1
-- Configure the source settings.
smu.source.highc = smu.OFF
smu.source.range = 5
-- smu.source.readback = smu.ON
smu.source.highc = smu.OFF
smu.source.ilimit.level = 1
-- Create a configuration list of current source levels
smu.source.configlist.create("VoltListSweep")
-- Add source levels to configuration list
for v = 1, 5 do
    smu.source.level = v
    smu.source.configlist.store("VoltListSweep")
end
-- Add Configuration List to Sweep
smu.source.sweeplist("VoltListSweep")
-- Start the sweep and wait for it to complete.
trigger.model.initiate()
waitcomplete()
-- Define values for next step.
voltage = defbuffer1.sourcevalues
current = defbuffer1
imax = current[1]
vmax = voltage[1]
pmax = voltage[1]*current[1]
-- Calculate Max Power, Current, and Voltage
for i = 1, 5 do
    print(voltage[i], current[i], voltage[i]*current[i])
    if (voltage[i]*current[i] > pmax) then
        pmax = voltage[i]*current[i]
        imax = current[i]
        vmax = voltage[i]
    end
end
pmax = math.abs(pmax)
imax = math.abs(imax)
print("Pmax = pmax, Imax = imax, Vmax = vmax")
-- Display values on the Model 2460 front panel.
display.changescreen(display.SCREEN_USER_SWIPE)
display.settext(display.TEXT1, string.format("Pmax = %.4fW", pmax))
display.settext(display.TEXT2, string.format("Imax = %.4fA, Vmax = %.2fV", imax, vmax))