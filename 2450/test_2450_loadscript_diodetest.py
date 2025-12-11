# this proves loadscript works...

import pyvisa

ADDRESS = "TCPIP0::169.254.188.69::5025::SOCKET"  # Keithley 2450 SMU
FORWARD_CURRENT = 1e-3  # 1 mA

TSP_SCRIPT = """loadscript DiodeTest
function config()
    reset()
    smu.source.func = smu.FUNC_DC_CURRENT
    smu.source.vlimit.level = 21
    smu.source.autorange = smu.ON
    smu.source.autodelay = smu.ON
    smu.measure.func = smu.FUNC_DC_VOLTAGE
    smu.measure.autorange = smu.ON
    smu.measure.nplc = 1
    display.changescreen(display.SCREEN_USER_SWIPE)
    display.settext(display.TEXT1, "Diode Test Ready")
    display.settext(display.TEXT2, "Awaiting trigger")
end

function forwardv(current)
    smu.source.level = current
    smu.source.output = smu.ON
    smu.measure.read()
    smu.source.output = smu.OFF
    local reading = defbuffer1.readings[defbuffer1.endindex]
    display.settext(display.TEXT1, string.format("I=%.4fmA", current * 1000))
    display.settext(display.TEXT2, string.format("V=%.4fV", reading))
    print(reading)
end
endscript"""


def main() -> None:
    rm = pyvisa.ResourceManager()
    instrument = None

    try:
        instrument = rm.open_resource(ADDRESS)
        instrument.timeout = 5000
        instrument.read_termination = "\n"
        instrument.write_termination = "\n"

        print(f"Loading DiodeTest script to {ADDRESS}...")
        instrument.write(TSP_SCRIPT)
        instrument.write("DiodeTest.save()")
        instrument.write("DiodeTest()")  # Make the functions available

        print("Configuring instrument...")
        instrument.write("config()")

        print(f"Triggering forward voltage measurement at {FORWARD_CURRENT} A...")
        measurement = instrument.query(f"forwardv({FORWARD_CURRENT})").strip()
        print(f"Forward voltage: {measurement} V")

    except pyvisa.VisaIOError as error:
        print(f"VISA communication failed: {error}")
    finally:
        if instrument is not None:
            instrument.close()
        rm.close()


if __name__ == "__main__":
    main()
