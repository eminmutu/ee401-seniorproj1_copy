import pyvisa

rm = pyvisa.ResourceManager()
address = "TCPIP0::169.254.188.69::5025::SOCKET"
inst = rm.open_resource(address)

# Critical for TCPIP SOCKET:
inst.read_termination = "\n"
inst.write_termination = "\n"
inst.timeout = 10000  # ms

inst.write("reset()")
inst.write("smu.source.func = smu.FUNC_DC_CURRENT")
inst.write("smu.source.vlimit.level = 21")
inst.write("smu.source.range = 0.01")
inst.write("smu.source.autodelay = smu.ON")
inst.write("smu.measure.func = smu.FUNC_DC_VOLTAGE")
inst.write("smu.measure.range = 21")
inst.write("smu.measure.nplc = 1")

currlist = [1E-7, 1E-6, 1E-5, 1E-4, 1E-3, 1E-2]
voltlist = [None] * len(currlist)

for i, current in enumerate(currlist):
    inst.write(f"smu.source.level = {current}")
    inst.write("smu.source.output = smu.ON")
    # Query directly; smu.measure.read() returns a value immediately
    voltlist[i] = float(inst.query("print(smu.measure.read())"))
    inst.write("smu.source.output = smu.OFF")

voltDiff = max(voltlist) - min(voltlist)
print(voltDiff)