"""
SDG1020 Senior Project Interface - Burst Tuning Edition
Includes explicit SET buttons for Burst Period and Burst Delay.
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
        self.root.title("SDG1020 Control - Burst Tuning")

        self.rm = None
        self.inst = None

        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        # --- Top Section: Connection & Waveform Params ---
        top = tk.Frame(root, padx=12, pady=12)
        top.grid(row=0, column=0, sticky="nsew")
        for col in range(4): 
            top.grid_columnconfigure(col, weight=1)

        # Row 0: Connection
        tk.Label(top, text="VISA Address:").grid(row=0, column=0, sticky="w")
        self.addr_var = tk.StringVar(value=DEFAULT_ADDR)
        tk.Entry(top, textvariable=self.addr_var).grid(
            row=0, column=1, columnspan=2, sticky="ew"
        )
        tk.Button(top, text="List", command=self.safe_run(self.list_resources)).grid(
            row=0, column=3, sticky="ew", padx=(6, 0)
        )

        # Row 1: Period & Amp
        tk.Label(top, text="Period (s):").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.period_var = tk.StringVar(value="1e-3")
        tk.Entry(top, textvariable=self.period_var).grid(row=1, column=1, sticky="ew", pady=(8, 0))

        tk.Label(top, text="Amplitude (Vpp):").grid(row=1, column=2, sticky="w", pady=(8, 0))
        self.amp_var = tk.StringVar(value="2.0")
        tk.Entry(top, textvariable=self.amp_var).grid(row=1, column=3, sticky="ew", pady=(8, 0))

        # Row 2: Width & Offset
        tk.Label(top, text="Pulse Width (s):").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.width_var = tk.StringVar(value="5e-4")
        tk.Entry(top, textvariable=self.width_var).grid(row=2, column=1, sticky="ew", pady=(6, 0))

        tk.Label(top, text="Offset (V):").grid(row=2, column=2, sticky="w", pady=(6, 0))
        self.offset_var = tk.StringVar(value="0.0")
        tk.Entry(top, textvariable=self.offset_var).grid(row=2, column=3, sticky="ew", pady=(6, 0))

        # Row 3: Pulse Delay (Standard Entry, removed explicit button per request)
        tk.Label(top, text="Pulse Delay (s):").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.pulse_dly_var = tk.StringVar(value="0.0")
        tk.Entry(top, textvariable=self.pulse_dly_var).grid(row=3, column=1, sticky="ew", pady=(6, 0))

        # --- Burst Section (Expanded Control) ---
        burst = tk.LabelFrame(root, text="Burst Settings (Explicit Control)", padx=12, pady=10)
        burst.grid(row=1, column=0, sticky="ew", pady=(0, 6), padx=12)
        # We need more columns for the "Set" buttons
        for col in range(6): burst.grid_columnconfigure(col, weight=1)

        # Row 0: Enable & Basic Params
        self.burst_enable = tk.BooleanVar(value=False)
        tk.Checkbutton(burst, text="Enable burst", variable=self.burst_enable).grid(row=0, column=0, sticky="w")

        tk.Label(burst, text="Cycles:").grid(row=0, column=1, sticky="e")
        self.burst_cycles_var = tk.StringVar(value="5")
        tk.Entry(burst, textvariable=self.burst_cycles_var, width=8).grid(row=0, column=2, sticky="w")

        tk.Label(burst, text="Trig Src:").grid(row=0, column=3, sticky="e")
        self.burst_source_var = tk.StringVar(value="INT")
        tk.OptionMenu(burst, self.burst_source_var, "INT", "EXT", "MAN").grid(row=0, column=4, sticky="w")

        # Row 1: Burst Period + Explicit SET Button
        tk.Label(burst, text="Burst Period (s):").grid(row=1, column=0, sticky="e", pady=5)
        self.burst_period_var = tk.StringVar(value="0.01")
        tk.Entry(burst, textvariable=self.burst_period_var).grid(row=1, column=1, columnspan=2, sticky="ew", pady=5)
        
        tk.Button(burst, text="Set Burst Period", command=self.safe_run(self.update_burst_period_only)).grid(
            row=1, column=3, columnspan=2, sticky="ew", padx=5, pady=5
        )

        # Row 2: Burst Delay + Explicit SET Button
        tk.Label(burst, text="Burst Delay (s):").grid(row=2, column=0, sticky="e", pady=5)
        self.burst_delay_var = tk.StringVar(value="0.0")
        tk.Entry(burst, textvariable=self.burst_delay_var).grid(row=2, column=1, columnspan=2, sticky="ew", pady=5)
        
        tk.Button(burst, text="Set Burst Delay", command=self.safe_run(self.update_burst_delay_only)).grid(
            row=2, column=3, columnspan=2, sticky="ew", padx=5, pady=5
        )

        # --- Buttons Section ---
        btns = tk.Frame(root, padx=12)
        btns.grid(row=2, column=0, sticky="ew", pady=(6, 6))
        for col in range(4): btns.columnconfigure(col, weight=1)

        self.btn_connect = tk.Button(btns, text="Connect", command=self.safe_run(self.connect))
        self.btn_connect.grid(row=0, column=0, sticky="ew")

        self.btn_disconnect = tk.Button(btns, text="Disconnect", state="disabled", command=self.safe_run(self.disconnect))
        self.btn_disconnect.grid(row=0, column=1, sticky="ew", padx=5)

        tk.Button(btns, text="Apply Full Config", command=self.safe_run(self.apply_pulse)).grid(row=0, column=2, sticky="ew", padx=5)
        tk.Button(btns, text="Query", command=self.safe_run(self.query_waveform)).grid(row=0, column=3, sticky="ew", padx=5)

        tk.Button(btns, text="Output ON", command=self.safe_run(self.output_on)).grid(row=1, column=0, columnspan=2, sticky="ew", pady=5)
        tk.Button(btns, text="Output OFF", command=self.safe_run(self.output_off)).grid(row=1, column=2, columnspan=2, sticky="ew", padx=5, pady=5)
        
        # Sync
        self.sync_state = tk.BooleanVar(value=False)
        tk.Checkbutton(btns, text="Rear Panel Sync Output ON", variable=self.sync_state, command=self.safe_run(self.toggle_sync)).grid(row=2, column=0, columnspan=4, sticky="ew", pady=5)

        # --- Log ---
        self.status_var = tk.StringVar(value="Disconnected")
        tk.Label(root, textvariable=self.status_var, anchor="w", padx=12).grid(row=3, column=0, sticky="ew")
        self.log = scrolledtext.ScrolledText(root, width=80, height=14, state="disabled")
        self.log.grid(row=4, column=0, padx=12, pady=(0, 12), sticky="nsew")

    # --- Core Functions ---
    def write_inst(self, cmd):
        if self.inst:
            self.inst.write(cmd)
            time.sleep(0.1) # Safety Delay
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

    # --- Connection & Resources ---
    def list_resources(self):
        """Lists available VISA resources (USB/GPIB devices)."""
        if self.rm is None:
            self.rm = pyvisa.ResourceManager()
        try:
            resources = self.rm.list_resources()
            msg = "Resources: " + (", ".join(resources) if resources else "<none>")
            self.log_message(msg)
        except Exception as e:
            self.log_message(f"Error listing resources: {e}")

    def connect(self):
        addr = self.addr_var.get().strip()
        self.rm = pyvisa.ResourceManager()
        if self.inst: self.inst.close()
        self.inst = self.rm.open_resource(addr)
        self.inst.timeout = 10000
        self.inst.write_termination = "\n"
        self.inst.read_termination = ""
        idn = self.inst.query("*IDN?").strip()
        self.inst = self.inst
        self.status_var.set(f"Connected: {addr}")
        self.btn_connect.config(state="disabled")
        self.btn_disconnect.config(state="normal")
        self.log_message(f"Connected: {idn}")

    def disconnect(self):
        if self.inst:
            self._disable_outputs()
            self.inst.close()
            self.inst = None
        self.status_var.set("Disconnected")
        self.btn_connect.config(state="normal")
        self.btn_disconnect.config(state="disabled")

    def _disable_outputs(self):
        if self.inst:
            for ch in ALL_CHANNELS:
                try: self.write_inst(f"C{ch}:OUTP OFF")
                except: pass

    # --- BURST UPDATE FUNCTIONS (Requested) ---
    def update_burst_period_only(self):
        self._require_inst()
        p_txt = self.burst_period_var.get().strip()
        if not p_txt: raise ValueError("Burst Period Empty")
        b_period = self._parse_time(p_txt)
        
        # Send just the Burst Period command
        self.write_inst(f"C{CHANNEL}:BTWV PRD,{b_period:.9g}")
        self.status_var.set(f"Updated Burst Period: {b_period}s")

    def update_burst_delay_only(self):
        self._require_inst()
        d_txt = self.burst_delay_var.get().strip()
        if not d_txt: raise ValueError("Burst Delay Empty")
        b_delay = self._parse_time(d_txt)
        
        # Send just the Burst Delay command
        self.write_inst(f"C{CHANNEL}:BTWV DLAY,{b_delay:.9g}")
        self.status_var.set(f"Updated Burst Delay: {b_delay}s")

    # --- Main Apply Function ---
    def apply_pulse(self):
        self._require_inst()
        period = self._parse_time(self.period_var.get())
        if period <= 0: raise ValueError("Period must be > 0")
        
        amp = float(self.amp_var.get())
        width = self._parse_time(self.width_var.get())
        if width <= 0 or width >= period: raise ValueError("Width must be > 0 and < Period")
        
        offset = float(self.offset_var.get())
        dly = self._parse_time(self.pulse_dly_var.get())
        duty = (width / period) * 100.0
        
        # 1. Set Pulse
        self.write_inst(f"C{CHANNEL}:BSWV WVTP,PULSE")
        self.write_inst(f"C{CHANNEL}:BSWV PERI,{period:.9g}")
        self.write_inst(f"C{CHANNEL}:BSWV AMP,{amp:.9g}")
        self.write_inst(f"C{CHANNEL}:BSWV OFST,{offset:.9g}")
        self.write_inst(f"C{CHANNEL}:BSWV DUTY,{duty:.9g}")
        self.write_inst(f"C{CHANNEL}:BSWV DLY,{dly:.9g}")

        # 2. Set Burst
        burst_msg = self._configure_burst(period)
        status = f"Pulse Set: T={period}s, Dly={dly}s"
        if burst_msg: status += f" | {burst_msg}"
        self.status_var.set(status)

    def output_on(self):
        self._require_inst()
        self.write_inst(f"C{CHANNEL}:OUTP ON")
        self.status_var.set("Output ON")

    def output_off(self):
        self._require_inst()
        self.write_inst(f"C{CHANNEL}:OUTP OFF")
        self.status_var.set("Output OFF")

    def toggle_sync(self):
        self._require_inst()
        state = "ON" if self.sync_state.get() else "OFF"
        self.write_inst(f"C{CHANNEL}:SYNC {state}")
        self.log_message(f"Sync Output {state}")

    def query_waveform(self):
        inst = self._require_inst()
        resp = inst.query(f"C{CHANNEL}:BSWV?").strip()
        self.log_message(f"Rx: {resp}")

    def _require_inst(self):
        if self.inst is None: raise RuntimeError("Instrument not connected")
        return self.inst

    @staticmethod
    def _parse_time(value: str) -> float:
        val = value.strip().lower()
        if not val: raise ValueError("Empty Value")
        suffixes = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "µs": 1e-6, "ns": 1e-9}
        for suf in sorted(suffixes, key=len, reverse=True):
            if val.endswith(suf):
                return float(val[: -len(suf)]) * suffixes[suf]
        return float(val)

    def _configure_burst(self, base_period):
        prefix = f"C{CHANNEL}:BTWV"
        if not self.burst_enable.get():
            self.write_inst(f"{prefix} STATE,OFF")
            return "Burst disabled"
        
        mode = "NCYC" # Fixed to NCYC for simplicity based on your use case
        source = self.burst_source_var.get().strip().upper() or "INT"
        cycles = int(float(self.burst_cycles_var.get().strip() or 1))
        
        p_txt = self.burst_period_var.get().strip()
        b_period = self._parse_time(p_txt) if p_txt else base_period
        
        d_txt = self.burst_delay_var.get().strip()
        b_delay = self._parse_time(d_txt) if d_txt else 0.0

        self.write_inst(f"{prefix} STATE,ON")
        self.write_inst(f"{prefix} GATE_NCYC,{mode}")
        self.write_inst(f"{prefix} TRSR,{source}")
        self.write_inst(f"{prefix} TIME,{cycles}")
        self.write_inst(f"{prefix} PRD,{b_period:.9g}")
        self.write_inst(f"{prefix} DLAY,{b_delay:.9g}")
        return f"Burst: {cycles} cyc"

def main():
    root = tk.Tk()
    app = SDG1020PulseGui(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.disconnect(), root.destroy()))
    root.mainloop()

if __name__ == "__main__":
    main()