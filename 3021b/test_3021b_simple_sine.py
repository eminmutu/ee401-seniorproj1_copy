import time

import pyvisa

ADDR = "TCPIP0::169.254.6.24::inst0::INSTR"
FREQ_HZ = 100_000
AMPLITUDE_VPP = 1.0
OFFSET_V = 0.0


def drain_errors(inst, prefix="[ERR] ", max_reads=6):
    for _ in range(max_reads):
        err = inst.query("SYSTem:ERRor?").strip()
        print(f"{prefix}{err}")
        if err.startswith("0,"):
            break


def main():
    rm = pyvisa.ResourceManager()
    inst = rm.open_resource(ADDR)
    inst.timeout = 5000
    inst.read_termination = "\n"
    inst.write_termination = "\n"

    try:
        print("Connected to:", inst.query("*IDN?").strip())

        inst.write("*CLS")
        inst.write("*RST")
        time.sleep(0.6)

        inst.write("OUTPut1:STATe OFF")
        inst.write("SOURce1:FUNCtion:SHAPe SIN")
        inst.write(f"SOURce1:FREQuency:FIXed {FREQ_HZ}")
        inst.write("SOURce1:VOLTage:UNIT VPP")
        inst.write(f"SOURce1:VOLTage:LEVel:IMMediate:AMPLitude {AMPLITUDE_VPP}")
        inst.write(f"SOURce1:VOLTage:LEVel:IMMediate:OFFSet {OFFSET_V}")

        inst.write("OUTPut1:STATe ON")
        time.sleep(0.25)

        print("Shape     :", inst.query("SOURce1:FUNCtion:SHAPe?").strip())
        print("Frequency :", inst.query("SOURce1:FREQuency:FIXed?").strip(), "Hz")
        print("Amplitude :", inst.query("SOURce1:VOLTage:LEVel:IMMediate:AMPLitude?").strip(), "Vpp")
        print("Offset    :", inst.query("SOURce1:VOLTage:LEVel:IMMediate:OFFSet?").strip(), "V")
        print("Output    :", inst.query("OUTPut1:STATe?").strip())

        drain_errors(inst)
    finally:
        try:
            inst.write("OUTPut1:STATe OFF")
            print("Output disabled.")
        except Exception as exc:
            print("Cleanup warning:", exc)
        try:
            inst.close()
        finally:
            rm.close()


if __name__ == "__main__":
    main()
