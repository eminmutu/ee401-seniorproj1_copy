import time

import pyvisa

ADDR = "TCPIP0::169.254.6.24::inst0::INSTR"
FREQ_HZ = 1_000
WIDTH_S = 50e-6
HIGH_LEVEL_V = 1.0
LOW_LEVEL_V = 0.0
LEADING_EDGE_S = 20e-9
TRAILING_EDGE_S = 20e-9
LOAD_SETTING = "INF"  # Use "INF" or provide a numeric impedance in ohms


def drain_errors(inst, prefix="[ERR] ", max_reads=8):
    for _ in range(max_reads):
        err = inst.query("SYSTem:ERRor?").strip()
        print(f"{prefix}{err}")
        if err.startswith("0,"):
            break


def main():
    if FREQ_HZ <= 0:
        raise ValueError("FREQ_HZ must be > 0.")
    if WIDTH_S <= 0:
        raise ValueError("WIDTH_S must be > 0.")

    period_s = 1.0 / FREQ_HZ
    if WIDTH_S >= period_s:
        raise ValueError("Pulse width must be smaller than the period.")

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

        if isinstance(LOAD_SETTING, str) and LOAD_SETTING.strip().upper() == "INF":
            inst.write("OUTPut1:IMPedance INF")
        elif LOAD_SETTING is not None:
            load_value = float(LOAD_SETTING)
            if load_value <= 0:
                raise ValueError("LOAD_SETTING must be > 0 when numeric.")
            inst.write(f"OUTPut1:IMPedance {load_value}")

        inst.write("SOURce1:FUNCtion:SHAPe PULSe")
        inst.write(f"SOURce1:PULSe:PERiod {period_s}")
        inst.write("SOURce1:PULSe:HOLD WIDTh")
        inst.write(f"SOURce1:PULSe:WIDTh {WIDTH_S}")

        inst.write(f"SOURce1:VOLTage:LEVel:IMMediate:HIGH {HIGH_LEVEL_V}")
        inst.write(f"SOURce1:VOLTage:LEVel:IMMediate:LOW {LOW_LEVEL_V}")

        if LEADING_EDGE_S is not None:
            inst.write(f"SOURce1:PULSe:TRANsition:LEADing {LEADING_EDGE_S}")
        if TRAILING_EDGE_S is not None:
            inst.write(f"SOURce1:PULSe:TRANsition:TRAiling {TRAILING_EDGE_S}")

        inst.write("SOURce1:PHASe 0")
        inst.write("OUTPut1:STATe ON")
        time.sleep(0.25)

        print("Shape     :", inst.query("SOURce1:FUNCtion:SHAPe?").strip())
        per = float(inst.query("SOURce1:PULSe:PERiod?").strip())
        print("Period    :", per, "s")
        if per != 0:
            print("Frequency :", 1.0 / per, "Hz")
        print("Width     :", inst.query("SOURce1:PULSe:WIDTh?").strip(), "s")
        print("High level:", inst.query("SOURce1:VOLTage:LEVel:IMMediate:HIGH?").strip(), "V")
        print("Low level :", inst.query("SOURce1:VOLTage:LEVel:IMMediate:LOW?").strip(), "V")
        print("Lead edge :", inst.query("SOURce1:PULSe:TRANsition:LEADing?").strip(), "s")
        print("Trail edge:", inst.query("SOURce1:PULSe:TRANsition:TRAiling?").strip(), "s")
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
