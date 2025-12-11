-- Clear any previously detected command interface triggers. 
trigger.clear() 
-- Turn on output. 
smua.source.output = smua.OUTPUT_ON 
-- Wait 30 seconds for a command interface trigger. 
triggered = trigger.wait(30) 
-- Get a voltage reading. 
reading = smua.measure.v() 
-- Send a command interface trigger to trigger the measurement. 
*TRG -- this *trg is invalid and should be the one sent from the keysight device

--[[ 

This should be implemented with Keysight somehow

The programming example below illustrates how to configure digital I/O line 2 as an input trigger and 
digital I/O line 14 as an output trigger. The 2600B to wait for an external input trigger on digital I/O line 
2. If a trigger event occurs, the 2600B outputs an external trigger on digital I/O line 14. If no trigger 
event is received on digital I/O line 2, the test is aborted.

-- Configure digital I/O lines 2 and 14 for input trigger detection 
-- and output trigger generation, respectively. 
digio.trigger[2].mode = digio.TRIG_RISINGA 
digio.trigger[2].clear()  
digio.trigger[14].mode = digio.TRIG_FALLING 
digio.trigger[14].pulsewidth = 0.0001 
-- Wait 15 seconds for a trigger event to occur on digital I/O line 2. 
trigInput = digio.trigger[2].wait(15) 
-- If a trigger event occurs on digital I/O line 2, assert an output 
-- trigger on digital I/O line 14. If a trigger event does  
-- not occur, turn off the output of smua and issue a message 
-- on the front-panel display. 
if trigInput == true then 
 digio.trigger[14].assert() 
else 
 smua.source.output = smua.OUTPUT_OFF 
 display.screen = display.USER 
 display.clear() 
 display.setcursor(1, 1) 
 display.settext("No trigger received. Test aborted.") 
 exit() 
end
]]