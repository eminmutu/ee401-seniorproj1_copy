import time

import pyvisa

ADDR = "TCPIP0::169.254.6.24::inst0::INSTR"
FREQ_HZ = 10_000
WIDTH_S = 20e-6
HIGH_LEVEL_V = 1.0
LOW_LEVEL_V = 0.0
LEADING_EDGE_S = 20e-9
TRAILING_EDGE_S = 20e-9
LOAD_SETTING = "INF"

BURST_MODE = "TRIGgered"  # TRIGgered or GATed
BURST_CYCLES = 5
BURST_DELAY_S = 0.0

TRIGGER_SOURCE = "TIMer"  # TIMer or EXTernal
TRIGGER_PERIOD_S = 0.05  # used only when TRIGGER_SOURCE == "TIMer"


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
    if BURST_CYCLES < 1:
        raise ValueError("BURST_CYCLES must be >= 1.")
    if TRIGGER_SOURCE not in {"TIMer", "EXTernal"}:
        raise ValueError("TRIGGER_SOURCE must be TIMer or EXTernal.")
    if BURST_MODE not in {"TRIGgered", "GATed"}:
        raise ValueError("BURST_MODE must be TRIGgered or GATed.")

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

        inst.write(f"SOURce1:BURSt:MODE {BURST_MODE}")
        inst.write(f"SOURce1:BURSt:NCYCles {BURST_CYCLES}")
        if BURST_MODE.upper().startswith("TRIG"):
            inst.write(f"SOURce1:BURSt:TDELay {BURST_DELAY_S}")
        inst.write("SOURce1:BURSt:STATe ON")

        inst.write(f"TRIGger:SEQuence:SOURce {TRIGGER_SOURCE}")
        if TRIGGER_SOURCE == "TIMer":
            if TRIGGER_PERIOD_S <= 0:
                raise ValueError("TRIGGER_PERIOD_S must be > 0 for TIMer source.")
            inst.write(f"TRIGger:SEQuence:TIMer {TRIGGER_PERIOD_S}")

        inst.write("SOURce1:PHASe 0")
        inst.write("OUTPut1:STATe ON")
        time.sleep(0.1)

        inst.write("TRIGger:SEQuence:IMMediate")
        time.sleep(BURST_CYCLES * period_s + BURST_DELAY_S + 0.5)

        print("Burst mode:", inst.query("SOURce1:BURSt:STATe?").strip())
        print("Burst mode type:", inst.query("SOURce1:BURSt:MODE?").strip())
        print("Burst cycles:", inst.query("SOURce1:BURSt:NCYCles?").strip())
        if BURST_MODE.upper().startswith("TRIG"):
            print("Burst delay:", inst.query("SOURce1:BURSt:TDELay?").strip(), "s")
        print("Trigger source:", inst.query("TRIGger:SEQuence:SOURce?").strip())
        if TRIGGER_SOURCE == "TIMer":
            print("Trigger period:", inst.query("TRIGger:SEQuence:TIMer?").strip(), "s")
        print("Output state:", inst.query("OUTPut1:STATe?").strip())

        drain_errors(inst)
    finally:
        try:
            inst.write("OUTPut1:STATe OFF")
            inst.write("SOURce1:BURSt:STATe OFF")
            print("Output disabled, burst off.")
        except Exception as exc:
            print("Cleanup warning:", exc)
        try:
            inst.close()
        finally:
            rm.close()


if __name__ == "__main__":
    main()
