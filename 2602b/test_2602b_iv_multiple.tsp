function run_single(v, comp)
    if v == nil then v = 1.0 end
    if comp == nil then comp = 0.5 end

    smua.reset()
    smua.source.func = smua.OUTPUT_DCVOLTS
    smua.source.levelv = v
    smua.source.limiti = comp
    smua.source.output = smua.OUTPUT_ON

    smua.nvbuffer1.appendmode = 1  -- Enable append mode to keep all measurements in the buffer
    
    smua.measure.i(smua.nvbuffer1)

    print(string.format("IV_SINGLE_DONE,%.6f,%.6f", v, comp))
end

function run_multiple(start_v, stop_v, step_v, comp)
    if start_v == nil then start_v = 0.0 end
    if stop_v == nil then stop_v = 3.0 end
    if step_v == nil then step_v = 1.0 end
    if comp == nil then comp = 0.5 end
    
    smua.nvbuffer1.clear()  -- Clear the buffer once before starting the loop

    local v = start_v
    while v <= stop_v do
        run_single(v, comp)  -- Call the single measurement function
        v = v + step_v
    end

    print("IV_MULTIPLE_DONE")
end

function print_all_buffer()
    local n = smua.nvbuffer1.n
    if n == 0 then
        print("BUF_EMPTY")
        return
    end

    print("BUF_ALL")
    for i = 1, n do
        local cur = smua.nvbuffer1.readings[i]  -- Current reading
        print(string.format("BUF[%d],I=%.12g", i, cur))
    end
end