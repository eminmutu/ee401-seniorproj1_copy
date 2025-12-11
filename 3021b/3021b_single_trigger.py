"""Standalone GUI for Tektronix AFG3021B.

Designed for Direct State Control with Split Triggering:
1. ARM HIGH: Configures Infinite Burst (Ready to Latch).
2. SEND TRIGGER: Sends *TRG (Executes the Latch or Pulse).
3. Output ON/OFF: Toggles main output.
"""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import pyvisa

DEFAULT_ADDRESS = "TCPIP0::169.254.6.24::inst0::INSTR"
DEFAULT_FREQ = "1000"
DEFAULT_WIDTH = "500e-6"
DEFAULT_AMPLITUDE = "1.0"
DEFAULT_OFFSET = "0.0"
DEFAULT_LEAD = "10e-9"
DEFAULT_TRAIL = "10e-9"
DEFAULT_DELAY = "0"
DEFAULT_LOAD = "INF"


class AFG3021BLatchPanel:
    """Encapsulates the AFG3021B controls with strict Latch logic."""

    def __init__(self, parent: tk.Misc) -> None:
        self.parent = parent
        self.rm: pyvisa.ResourceManager | None = None
        self.inst: pyvisa.resources.MessageBasedResource | None = None
        self.connected = False
        self.output_on = False

        # --- Variables ---
        self.addr_var = tk.StringVar(value=DEFAULT_ADDRESS)
        
        # Channel 1 Pulse Parameters
        self.freq_var = tk.StringVar(value=DEFAULT_FREQ)
        self.width_var = tk.StringVar(value=DEFAULT_WIDTH)
        self.amp_var = tk.StringVar(value=DEFAULT_AMPLITUDE)
        self.offset_var = tk.StringVar(value=DEFAULT_OFFSET)
        self.lead_var = tk.StringVar(value=DEFAULT_LEAD)
        self.trail_var = tk.StringVar(value=DEFAULT_TRAIL)
        self.delay_var = tk.StringVar(value=DEFAULT_DELAY)
        self.load_var = tk.StringVar(value=DEFAULT_LOAD)
        
        # Period Hint
        self.period_hint_var = tk.StringVar(value="Period: —")

        self._build_ui(parent)
        
        # Trace for period hint
        try:
            self.freq_var.trace_add("write", lambda *_: self._update_period_hint())
        except AttributeError:
            self.freq_var.trace("w", lambda *_: self._update_period_hint())
        self._update_period_hint()

    def _build_ui(self, frame: tk.Misc) -> None:
        container = ttk.Frame(frame, padding=10)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(1, weight=1)

        # --- 1. Connection ---
        ttk.Label(container, text="VISA address:").grid(column=0, row=0, sticky="w")
        ttk.Entry(container, textvariable=self.addr_var, width=32).grid(
            column=1, row=0, sticky="we", padx=(4, 8)
        )
        btns = ttk.Frame(container)
        btns.grid(column=0, row=1, columnspan=2, sticky="w", pady=(6, 0))
        self.btn_connect = ttk.Button(btns, text="Connect", command=self.connect)
        self.btn_connect.pack(side=tk.LEFT)
        self.btn_disconnect = ttk.Button(btns, text="Disconnect", command=self.disconnect, state="disabled")
        self.btn_disconnect.pack(side=tk.LEFT, padx=6)

        # --- 2. Channel 1 Configuration ---
        cfg = ttk.LabelFrame(container, text="Channel 1 Pulse Settings")
        cfg.grid(column=0, row=2, columnspan=2, sticky="ew", pady=(10, 0))
        for col in range(4):
            cfg.columnconfigure(col, weight=1)

        # Row 0: Frequency & Width
        ttk.Label(cfg, text="Frequency (Hz)").grid(column=0, row=0, sticky="e", pady=5)
        f_frame = ttk.Frame(cfg)
        f_frame.grid(column=1, row=0, sticky="w")
        ttk.Entry(f_frame, textvariable=self.freq_var, width=12).pack(side=tk.LEFT)
        ttk.Label(f_frame, textvariable=self.period_hint_var).pack(side=tk.LEFT, padx=(5, 0))

        ttk.Label(cfg, text="Width (s)").grid(column=2, row=0, sticky="e")
        ttk.Entry(cfg, textvariable=self.width_var, width=12).grid(column=3, row=0, sticky="w")

        # Row 1: Amplitude & Offset
        ttk.Label(cfg, text="Amplitude (Vpp)").grid(column=0, row=1, sticky="e", pady=5)
        ttk.Entry(cfg, textvariable=self.amp_var, width=12).grid(column=1, row=1, sticky="w")

        ttk.Label(cfg, text="Offset (V)").grid(column=2, row=1, sticky="e")
        ttk.Entry(cfg, textvariable=self.offset_var, width=12).grid(column=3, row=1, sticky="w")

        # Row 2: Edges
        ttk.Label(cfg, text="Rise Time (s)").grid(column=0, row=2, sticky="e", pady=5)
        ttk.Entry(cfg, textvariable=self.lead_var, width=12).grid(column=1, row=2, sticky="w")

        ttk.Label(cfg, text="Fall Time (s)").grid(column=2, row=2, sticky="e")
        ttk.Entry(cfg, textvariable=self.trail_var, width=12).grid(column=3, row=2, sticky="w")

        # Row 3: Load & Delay
        ttk.Label(cfg, text="Load (Ω or INF)").grid(column=0, row=3, sticky="e", pady=5)
        ttk.Entry(cfg, textvariable=self.load_var, width=12).grid(column=1, row=3, sticky="w")

        ttk.Label(cfg, text="Delay (s)").grid(column=2, row=3, sticky="e")
        ttk.Entry(cfg, textvariable=self.delay_var, width=12).grid(column=3, row=3, sticky="w")

        # --- 3. Manual Latch Controls ---
        ctrl = ttk.LabelFrame(container, text="Manual State Control")
        ctrl.grid(column=0, row=3, columnspan=2, sticky="ew", pady=(10, 0))
        
        # Status Label
        ttk.Label(ctrl, text="STATUS:").grid(row=0, column=0, padx=10, pady=10)
        self.lbl_status = ttk.Label(ctrl, text="DISCONNECTED", foreground="gray", font=("Helvetica", 10, "bold"))
        self.lbl_status.grid(row=0, column=1, sticky="w")

        btn_row = ttk.Frame(ctrl)
        btn_row.grid(row=1, column=0, columnspan=4, sticky="ew", padx=10, pady=10)
        
        # BUTTON 1: ARM HIGH (Setup Infinite, do NOT trigger)
        self.btn_high = ttk.Button(btn_row, text="ARM HIGH (Infinite)", command=self.fire_high, state="disabled")
        self.btn_high.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # BUTTON 2: SEND TRIGGER (*TRG)
        self.btn_trig = ttk.Button(btn_row, text="SEND TRIGGER", command=self.send_trigger, state="disabled")
        self.btn_trig.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # BUTTON 3: OUTPUT
        self.btn_output = ttk.Button(btn_row, text="Output: OFF", command=self.toggle_output, state="disabled")
        self.btn_output.pack(side=tk.LEFT, padx=5)

        # --- 4. Log ---
        self.log = scrolledtext.ScrolledText(container, height=12, state=tk.DISABLED)
        self.log.grid(column=0, row=4, columnspan=2, sticky="nsew", pady=(10, 0))
        container.rowconfigure(4, weight=1)

    # --- Utilities ---
    def _log(self, *parts: object) -> None:
        msg = " ".join(str(p) for p in parts)
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    @staticmethod
    def _parse_float_si(text: str, field_name: str) -> float:
        raw = text.strip().replace(" ", "")
        multipliers = {'k': 1e3, 'M': 1e6, 'm': 1e-3, 'u': 1e-6, 'n': 1e-9}
        if not raw: raise ValueError(f"{field_name} is required.")
        if raw[-1] in multipliers and raw[:-1].replace('.', '', 1).isdigit():
             return float(raw[:-1]) * multipliers[raw[-1]]
        try: return float(raw)
        except ValueError: return AFG3021BLatchPanel._parse_time_to_seconds(text, field_name)

    @staticmethod
    def _parse_time_to_seconds(text: str, field_name: str) -> float:
        raw = text.strip().lower().replace(" ", "")
        if not raw: raise ValueError(f"{field_name} is required.")
        units = { "s": 1.0, "ms": 1e-3, "us": 1e-6, "\u00b5s": 1e-6, "ns": 1e-9, "ps": 1e-12, "khz": 1000.0, "hz": 1.0, "mhz": 1e6 }
        for suffix in sorted(units, key=len, reverse=True):
            if raw.endswith(suffix):
                try: return float(raw[: -len(suffix)]) * units[suffix]
                except ValueError: pass
        return float(raw)
        
    @staticmethod
    def _format_seconds_si(seconds: float) -> str:
        value = float(seconds)
        if value <= 0 or not math.isfinite(value): return "—"
        if value >= 1: return f"{value:g} s"
        if value >= 1e-3: return f"{value*1e3:g} ms"
        if value >= 1e-6: return f"{value*1e6:g} us"
        if value >= 1e-9: return f"{value*1e9:g} ns"
        return f"{value*1e12:g} ps"

    def _update_period_hint(self) -> None:
        try:
            val = self._parse_float_si(self.freq_var.get(), "Frequency")
            if val > 0: self.period_hint_var.set(f"Period ≈ {self._format_seconds_si(1.0/val)}")
            else: self.period_hint_var.set("Period: —")
        except: self.period_hint_var.set("Period: —")

    def _set_status(self, text, color):
        self.lbl_status.config(text=text, foreground=color)

    # --- Connectivity ---
    def connect(self) -> None:
        if self.connected: return
        addr = self.addr_var.get().strip()
        if not addr:
            messagebox.showerror("Error", "VISA address required.")
            return
        try:
            self.rm = pyvisa.ResourceManager()
            self.inst = self.rm.open_resource(addr, timeout=5000)
            self.inst.write_termination = "\n" 
            self.inst.read_termination = "\n"
            idn = self.inst.query("*IDN?").strip()
            self._log(f"Connected: {idn}")
            self.connected = True
            
            # Enable controls
            self.btn_connect.configure(state="disabled")
            self.btn_disconnect.configure(state="normal")
            self.btn_high.configure(state="normal")
            self.btn_trig.configure(state="normal")
            self.btn_output.configure(state="normal")
            
            self._set_status("CONNECTED (Idle)", "orange")

        except Exception as e:
            self._log(f"Connection Error: {e}")
            messagebox.showerror("Error", str(e))

    def disconnect(self) -> None:
        if not self.connected: return
        try: 
            if self.inst:
                self.inst.write("SOURce1:BURSt:STATe OFF")
                self.inst.write("OUTPut1:STATe OFF")
                self.inst.close()
        except: pass
        self.inst = None
        self.connected = False
        self._log("Disconnected.")
        self.btn_connect.configure(state="normal")
        self.btn_disconnect.configure(state="disabled")
        self.btn_high.configure(state="disabled")
        self.btn_trig.configure(state="disabled")
        self.btn_output.configure(state="disabled")
        self._set_status("DISCONNECTED", "gray")

    # --- Core Logic ---

    def _apply_config(self):
        if not self.inst: return
        
        freq = self._parse_float_si(self.freq_var.get(), "Frequency")
        width = self._parse_time_to_seconds(self.width_var.get(), "Width")
        amp = self._parse_float_si(self.amp_var.get(), "Amplitude")
        offset = self._parse_float_si(self.offset_var.get(), "Offset")
        lead = self._parse_time_to_seconds(self.lead_var.get(), "Rise Time")
        trail = self._parse_time_to_seconds(self.trail_var.get(), "Fall Time")
        delay = self._parse_time_to_seconds(self.delay_var.get(), "Delay")
        load_str = self.load_var.get().strip().upper()

        self.inst.write("*CLS")
        
        if load_str in ["INF", "INFINITE", "HIGHZ"]: self.inst.write("OUTPut1:IMPedance INF")
        else:
            try: self.inst.write(f"OUTPut1:IMPedance {float(load_str)}")
            except: self.inst.write("OUTPut1:IMPedance 50")

        self.inst.write("SOURce1:FUNCtion:SHAPe PULSe")
        self.inst.write(f"SOURce1:FREQuency:FIXed {freq}")
        self.inst.write(f"SOURce1:PULSe:WIDTh {width}")
        self.inst.write(f"SOURce1:PULSe:DELay {delay}")
        self.inst.write(f"SOURce1:PULSe:TRANsition:LEADing {lead}")
        self.inst.write(f"SOURce1:PULSe:TRANsition:TRAiling {trail}")
        self.inst.write(f"SOURce1:VOLTage:LEVel:IMMediate:AMPLitude {amp}")
        self.inst.write(f"SOURce1:VOLTage:LEVel:IMMediate:OFFSet {offset}")

    def fire_high(self) -> None:
        """
        LATCH HIGH (Config Only):
        Forces the line High by starting an Infinite Burst.
        Does NOT trigger immediately (requires manual trigger).
        """
        if not self.inst: return
        try:
            self._apply_config()
            
            # Setup Infinite
            self.inst.write("SOURce1:BURSt:STATe ON")
            self.inst.write("SOURce1:BURSt:MODE TRIGgered")
            self.inst.write("TRIGger:SEQuence:SOURce BUS")
            self.inst.write("OUTPut:TRIGger:MODE SYNC")
            self.inst.write("SOURce1:BURSt:NCYCles INFinity")
            
            # Fire (Commented out per user request)
            # self.inst.write("*TRG")
            
            self._log("ARMED HIGH (Infinite). Waiting for Trigger.")
            self._set_status("ARMED HIGH", "blue")
            
        except Exception as e:
            self._log(f"High Error: {e}")
            messagebox.showerror("Error", str(e))

    def send_trigger(self) -> None:
        """
        SEND TRIGGER:
        Simply sends *TRG to the device.
        """
        if not self.inst: return
        try:
            self.inst.write("*TRG")
            self._log("Trigger Sent (*TRG).")
            # We don't change status because it depends on whether we are latched high or pulsing low
            
        except Exception as e:
            self._log(f"Trigger Error: {e}")
            messagebox.showerror("Error", str(e))

    def toggle_output(self) -> None:
        if not self.inst: return
        try:
            self.output_on = not self.output_on
            cmd = "ON" if self.output_on else "OFF"
            self.inst.write(f"OUTPut1:STATe {cmd}")
            self.btn_output.configure(text=f"Output: {cmd}")
            self._log(f"Output set to {cmd}")
        except Exception as e:
            self._log(f"Toggle Error: {e}")

class AFG3021BApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("AFG3021B State Controller")
        self.root.geometry("800x700")
        
        wrapper = ttk.Frame(self.root, padding=10)
        wrapper.pack(fill=tk.BOTH, expand=True)
        
        self.panel = AFG3021BLatchPanel(wrapper)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_close(self) -> None:
        try: self.panel.disconnect()
        except: pass
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()

if __name__ == "__main__":
    AFG3021BApp().run()