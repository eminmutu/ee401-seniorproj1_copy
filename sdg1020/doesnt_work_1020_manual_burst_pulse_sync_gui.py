"""
SDG1020 Senior Project Interface - "Software Burst" Button
Defaults:
- Pulse: 1us Period, 0.5us Width (Reverted as requested).
- Burst: 50us Delay.
- Software Button: Forces a 10s burst period temporarily to ensure ONLY ONE burst fires.
"""

import threading
import tkinter as tk
from tkinter import scrolledtext
import pyvisa
import time

# Your specific device address
DEFAULT_ADDR = "USB0::0xF4ED::0xEE3A::NDG10GA1160419::INSTR"
CHANNEL = 1
ALL_CHANNELS = (1, 2)

class SDG1020PulseGui:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("SDG1020 Control - Software Burst")

        self.rm = None
        self.inst = None

        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        # --- Top Section: Connection & Waveform Params ---
        top = tk.Frame(root, padx=12, pady=12)
        top.grid(row=0, column=0, sticky="nsew")
        for col in range(4): 
            top.grid_columnconfigure(col, weight=1)

        # Connection
        tk.Label(top, text="VISA Address:").grid(row=0, column=0, sticky="w")
        self.addr_var = tk.StringVar(value=DEFAULT_ADDR)
        tk.Entry(top, textvariable=self.addr_var).grid(row=0, column=1, columnspan=2, sticky="ew")
        tk.Button(top, text="List", command=self.safe_run(self.list_resources)).grid(row=0, column=3, sticky="ew", padx=(6, 0))

        # Pulse Settings (Reverted to your requested defaults)
        tk.Label(top, text="Period (s):").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.period_var = tk.StringVar(value="1e-6") # 1us
        tk.Entry(top, textvariable=self.period_var).grid(row=1, column=1, sticky="ew", pady=(8, 0))

        tk.Label(top, text="Amplitude (Vpp):").grid(row=1, column=2, sticky="w", pady=(8, 0))
        self.amp_var = tk.StringVar(value="2.0")
        tk.Entry(top, textvariable=self.amp_var).grid(row=1, column=3, sticky="ew", pady=(8, 0))

        tk.Label(top, text="Pulse Width (s):").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.width_var = tk.StringVar(value="0.5e-6") # 0.5us
        tk.Entry(top, textvariable=self.width_var).grid(row=2, column=1, sticky="ew", pady=(6, 0))

        tk.Label(top, text="Offset (V):").grid(row=2, column=2, sticky="w", pady=(6, 0))
        self.offset_var = tk.StringVar(value="0.0")
        tk.Entry(top, textvariable=self.offset_var).grid(row=2, column=3, sticky="ew", pady=(6, 0))

        tk.Label(top, text="Pulse Delay (s):").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.pulse_dly_var = tk.StringVar(value="0.0")
        tk.Entry(top, textvariable=self.pulse_dly_var).grid(row=3, column=1, sticky="ew", pady=(6, 0))

        # --- Burst Section ---
        burst = tk.LabelFrame(root, text="Burst Settings", padx=12, pady=10)
        burst.grid(row=1, column=0, sticky="ew", pady=(0, 6), padx=12)
        for col in range(6): burst.grid_columnconfigure(col, weight=1)

        self.burst_enable = tk.BooleanVar(value=True) 
        tk.Checkbutton(burst, text="Enable burst", variable=self.burst_enable).grid(row=0, column=0, sticky="w")

        tk.Label(burst, text="Cycles:").grid(row=0, column=1, sticky="e")
        self.burst_cycles_var = tk.StringVar(value="5")
        tk.Entry(burst, textvariable=self.burst_cycles_var, width=8).grid(row=0, column=2, sticky="w")

        tk.Label(burst, text="Trig Src:").grid(row=0, column=3, sticky="e")
        # Defaults to INT because our Software Button logic uses INT
        self.burst_source_var = tk.StringVar(value="INT") 
        tk.OptionMenu(burst, self.burst_source_var, "INT", "EXT", "MAN").grid(row=0, column=4, sticky="w")

        # Burst Period (Display only - Button will override this to 10s)
        tk.Label(burst, text="Burst Period (s):").grid(row=1, column=0, sticky="e", pady=5)
        self.burst_period_var = tk.StringVar(value="100e-6") 
        tk.Entry(burst, textvariable=self.burst_period_var).grid(row=1, column=1, columnspan=2, sticky="ew", pady=5)
        
        # Burst Delay
        tk.Label(burst, text="Burst Delay (s):").grid(row=2, column=0, sticky="e", pady=5)
        self.burst_delay_var = tk.StringVar(value="50e-6")
        tk.Entry(burst, textvariable=self.burst_delay_var).grid(row=2, column=1, columnspan=2, sticky="ew", pady=5)

        # --- THE SOFTWARE BURST BUTTON ---
        # This button executes the logic: Sync/Out ON -> Wait -> Sync/Out OFF
        self.btn_fire = tk.Button(burst, text="SOFTWARE BURST\n(Click for Single Shot)", bg="#d1e7dd", 
                                  command=self.safe_run(self.fire_software_burst))
        self.btn_fire.grid(row=0, column=5, rowspan=3, sticky="nsew", padx=10, pady=5)

        # --- Buttons Section ---
        btns = tk.Frame(root, padx=12)
        btns.grid(row=2, column=0, sticky="ew", pady=(6, 6))
        for col in range(4): btns.columnconfigure(col, weight=1)

        self.btn_connect = tk.Button(btns, text="Connect", command=self.safe_run(self.connect))
        self.btn_connect.grid(row=0, column=0, sticky="ew")

        self.btn_disconnect = tk.Button(btns, text="Disconnect", state="disabled", command=self.safe_run(self.disconnect))
        self.btn_disconnect.grid(row=0, column=1, sticky="ew", padx=5)

        tk.Button(btns, text="Apply Config", command=self.safe_run(self.apply_pulse)).grid(row=0, column=2, sticky="ew", padx=5)
        tk.Button(btns, text="Query", command=self.safe_run(self.query_waveform)).grid(row=0, column=3, sticky="ew", padx=5)

        # Separate controls for Sync/Output (if needed manually)
        tk.Button(btns, text="Output ON", command=self.safe_run(self.output_on)).grid(row=1, column=0, columnspan=2, sticky="ew", pady=5)
        tk.Button(btns, text="Output OFF", command=self.safe_run(self.output_off)).grid(row=1, column=2, columnspan=2, sticky="ew", padx=5, pady=5)
        
        self.sync_state = tk.BooleanVar(value=True)
        tk.Checkbutton(btns, text="Sync Output ON", variable=self.sync_state, command=self.safe_run(self.toggle_sync)).grid(row=2, column=0, columnspan=4, sticky="ew", pady=5)

        # Log
        self.status_var = tk.StringVar(value="Disconnected")
        tk.Label(root, textvariable=self.status_var, anchor="w", padx=12).grid(row=3, column=0, sticky="ew")
        self.log = scrolledtext.ScrolledText(root, width=80, height=14, state="disabled")
        self.log.grid(row=4, column=0, padx=12, pady=(0, 12), sticky="nsew")

    # --- Core Helpers ---
    def write_inst(self, cmd):
        if self.inst:
            self.inst.write(cmd)
            time.sleep(0.05) # Small delay for stability
            self.log_message(f"Tx: {cmd}")

    def safe_run(self, func):
        def _runner():
            try: func()
            except Exception as e: self.log_message(f"Error: {e}")
        return lambda: threading.Thread(target=_runner, daemon=True).start()

    def log_message(self, msg):
        self.log.config(state="normal")
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)
        self.log.config(state="disabled")

    # --- Connection ---
    def list_resources(self):
        if self.rm is None: self.rm = pyvisa.ResourceManager()
        try:
            resources = self.rm.list_resources()
            msg = "Resources: " + (", ".join(resources) if resources else "<none>")
            self.log_message(msg)
        except Exception as e: self.log_message(f"Error: {e}")

    def connect(self):
        addr = self.addr_var.get().strip()
        self.rm = pyvisa.ResourceManager()
        if self.inst: self.inst.close()
        self.inst = self.rm.open_resource(addr)
        self.inst.timeout = 10000
        self.inst.read_termination = ""
        idn = self.inst.query("*IDN?").strip()
        self.inst = self.inst
        self.status_var.set(f"Connected: {addr}")
        self.btn_connect.config(state="disabled")
        self.btn_disconnect.config(state="normal")
        self.log_message(f"Connected: {idn}")

    def disconnect(self):
        if self.inst:
            self.write_inst(f"C{CHANNEL}:OUTP OFF") # Safety off
            self.inst.close()
            self.inst = None
        self.status_var.set("Disconnected")
        self.btn_connect.config(state="normal")
        self.btn_disconnect.config(state="disabled")

    # --- THE SOFTWARE BURST LOGIC ---
    def fire_software_burst(self):
        """
        Executes a single burst event controlled by the PC.
        Logic:
        1. Set Burst Period to 10s (To prevent the 2nd cycle from firing).
        2. Turn Output & Sync ON.
        3. Wait 0.1s (Enough time for the 5 pulses to complete).
        4. Turn Output & Sync OFF immediately.
        """
        self._require_inst()
        
        # 1. Setup Safe Burst
        # We MUST use INT trigger with a long period. MTRG is broken on this unit.
        # If we used 100us burst period, the 2nd cycle would fire before Python could stop it.
        self.write_inst(f"C{CHANNEL}:BTWV TRSR,INT")
        self.write_inst(f"C{CHANNEL}:BTWV PRD,10.0") 
        
        # 2. Fire (Output & Sync ON)
        # Note: Sync usually follows Output, but we force it ON just in case.
        self.write_inst(f"C{CHANNEL}:SYNC ON")
        self.write_inst(f"C{CHANNEL}:OUTP ON")
        
        # 3. Wait (Duration of burst)
        # 5 cycles * 1us = 5us total duration.
        # 0.1s sleep is more than enough to capture it, but short enough to feel "instant".
        time.sleep(0.1) 
        
        # 4. Stop (Output & Sync OFF)
        self.write_inst(f"C{CHANNEL}:OUTP OFF")
        self.write_inst(f"C{CHANNEL}:SYNC OFF")
        
        self.log_message(f"SOFTWARE BURST: Fired & Closed.")

    # --- Standard Apply ---
    def apply_pulse(self):
        self._require_inst()
        
        # Helper to parse values
        def parse(v): 
            val = v.get().lower().replace('us','e-6').replace('ms','e-3').replace('ns','e-9')
            return float(val)

        period = parse(self.period_var)
        width = parse(self.width_var)
        amp = float(self.amp_var.get())
        offset = float(self.offset_var.get())
        dly = parse(self.pulse_dly_var)
        duty = (width / period) * 100.0

        # Burst Params
        b_cycles = int(self.burst_cycles_var.get())
        b_delay = parse(self.burst_delay_var)
        # We don't apply burst period here because the button overrides it
        
        # Send Pulse Commands
        self.write_inst(f"C{CHANNEL}:BSWV WVTP,PULSE")
        self.write_inst(f"C{CHANNEL}:BSWV PERI,{period:.9g}")
        self.write_inst(f"C{CHANNEL}:BSWV AMP,{amp:.9g}")
        self.write_inst(f"C{CHANNEL}:BSWV OFST,{offset:.9g}")
        self.write_inst(f"C{CHANNEL}:BSWV DUTY,{duty:.9g}")
        self.write_inst(f"C{CHANNEL}:BSWV DLY,{dly:.9g}")

        # Send Burst Commands (Enable INT trigger mode for our software trick)
        self.write_inst(f"C{CHANNEL}:BTWV STATE,ON")
        self.write_inst(f"C{CHANNEL}:BTWV GATE_NCYC,NCYC")
        self.write_inst(f"C{CHANNEL}:BTWV TIME,{b_cycles}")
        self.write_inst(f"C{CHANNEL}:BTWV DLAY,{b_delay:.9g}")
        
        self.status_var.set("Config Applied. Ready for Software Burst.")

    def output_on(self):
        self._require_inst()
        self.write_inst(f"C{CHANNEL}:OUTP ON")

    def output_off(self):
        self._require_inst()
        self.write_inst(f"C{CHANNEL}:OUTP OFF")

    def toggle_sync(self):
        self._require_inst()
        state = "ON" if self.sync_state.get() else "OFF"
        self.write_inst(f"C{CHANNEL}:SYNC {state}")

    def query_waveform(self):
        inst = self._require_inst()
        self.log_message(inst.query(f"C{CHANNEL}:BSWV?").strip())

    def _require_inst(self):
        if self.inst is None: raise RuntimeError("Not Connected")
        return self.inst

def main():
    root = tk.Tk()
    app = SDG1020PulseGui(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.disconnect(), root.destroy()))
    root.mainloop()

if __name__ == "__main__":
    main()