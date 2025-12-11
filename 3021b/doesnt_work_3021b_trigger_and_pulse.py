"""
Standalone GUI for Tektronix AFG3021B - Burst & Sync Controller.

Specific Features for User:
1. Burst Mode Default: Configured for 10 Cycles.
2. Sync Line Behavior: The Sync/Trigger Out line is SILENT (Low) until the burst fires.
   It goes High during the 10 cycles, then Low again.
3. Fire & Auto-Off: The Trigger button calculates the burst duration, fires the pulse,
   waits for it to finish, and then physically turns the Output Relay OFF.
"""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
import time
import threading

import pyvisa

# --- Constants & Defaults ---
DEFAULT_ADDRESS = "TCPIP0::169.254.6.24::inst0::INSTR"
DEFAULT_FREQ = "1000"       # 1 kHz
DEFAULT_WIDTH = "500e-6"    # 500 us
DEFAULT_AMPLITUDE = "1.0"   # 1Vpp
DEFAULT_OFFSET = "0.0"      # 0V Offset
DEFAULT_LEAD = "10e-9"
DEFAULT_TRAIL = "10e-9"
DEFAULT_DELAY = "0"
DEFAULT_CYCLES = "10"       # User requested 10 cycles
DEFAULT_LOAD = "INF"        # High Impedance load

class AFG3021BBurstPanel:
    """Encapsulates the AFG3021B controls with strict 10-cycle Burst logic."""

    def __init__(self, parent: tk.Misc) -> None:
        self.parent = parent
        self.rm: pyvisa.ResourceManager | None = None
        self.inst: pyvisa.resources.MessageBasedResource | None = None
        self.connected = False
        self.output_on = False
        self.latched_zero = False

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
        
        # Mode & Burst
        self.run_mode_var = tk.StringVar(value="Burst") # Default to Burst
        self.burst_count_var = tk.StringVar(value=DEFAULT_CYCLES)
        
        # Logic options
        self.auto_off_var = tk.BooleanVar(value=True) # "Then turn output off"

        # Period Hint
        self.period_hint_var = tk.StringVar(value="Period: —")

        self._build_ui(parent)
        
        # Trace for period hint
        try:
            self.freq_var.trace_add("write", lambda *_: self._update_period_hint())
            self.run_mode_var.trace_add("write", lambda *_: self._update_mode_ui())
        except AttributeError:
            self.freq_var.trace("w", lambda *_: self._update_period_hint())
            self.run_mode_var.trace("w", lambda *_: self._update_mode_ui())
        
        self._update_period_hint()
        self._update_mode_ui()

    def _build_ui(self, frame: tk.Misc) -> None:
        container = ttk.Frame(frame, padding=10)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(1, weight=1)

        # --- 1. Connection ---
        con_frame = ttk.Frame(container)
        con_frame.grid(column=0, row=0, columnspan=2, sticky="ew", pady=(0, 10))
        
        ttk.Label(con_frame, text="VISA Address:").pack(side=tk.LEFT)
        ttk.Entry(con_frame, textvariable=self.addr_var, width=30).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        self.btn_connect = ttk.Button(con_frame, text="Connect", command=self.connect)
        self.btn_connect.pack(side=tk.LEFT)
        self.btn_disconnect = ttk.Button(con_frame, text="Disconnect", command=self.disconnect, state="disabled")
        self.btn_disconnect.pack(side=tk.LEFT, padx=5)

        # --- 2. Channel 1 Configuration ---
        cfg = ttk.LabelFrame(container, text="Pulse Settings (10 Cycles)")
        cfg.grid(column=0, row=2, columnspan=2, sticky="ew", pady=(0, 10))
        for col in range(4): cfg.columnconfigure(col, weight=1)

        # Row 0
        ttk.Label(cfg, text="Frequency (Hz)").grid(column=0, row=0, sticky="e", pady=5)
        f_frame = ttk.Frame(cfg)
        f_frame.grid(column=1, row=0, sticky="w")
        ttk.Entry(f_frame, textvariable=self.freq_var, width=10).pack(side=tk.LEFT)
        ttk.Label(f_frame, textvariable=self.period_hint_var, foreground="blue").pack(side=tk.LEFT, padx=(5, 0))

        ttk.Label(cfg, text="Width (s)").grid(column=2, row=0, sticky="e")
        ttk.Entry(cfg, textvariable=self.width_var, width=12).grid(column=3, row=0, sticky="w")

        # Row 1
        ttk.Label(cfg, text="Amplitude (Vpp)").grid(column=0, row=1, sticky="e", pady=5)
        ttk.Entry(cfg, textvariable=self.amp_var, width=12).grid(column=1, row=1, sticky="w")

        ttk.Label(cfg, text="Offset (V)").grid(column=2, row=1, sticky="e")
        ttk.Entry(cfg, textvariable=self.offset_var, width=12).grid(column=3, row=1, sticky="w")

        # Row 2
        ttk.Label(cfg, text="Burst Cycles").grid(column=0, row=2, sticky="e", pady=5)
        self.ent_burst = ttk.Entry(cfg, textvariable=self.burst_count_var, width=12)
        self.ent_burst.grid(column=1, row=2, sticky="w")
        
        ttk.Label(cfg, text="Run Mode").grid(column=2, row=2, sticky="e")
        mode_cb = ttk.Combobox(cfg, textvariable=self.run_mode_var, values=("Burst", "Continuous"), state="readonly", width=10)
        mode_cb.grid(column=3, row=2, sticky="w")

        # --- 3. Action Controls ---
        ctrl = ttk.LabelFrame(container, text="Trigger Control")
        ctrl.grid(column=0, row=3, columnspan=2, sticky="ew", pady=(0, 10))
        
        # Status
        status_frame = ttk.Frame(ctrl)
        status_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(status_frame, text="STATUS:").pack(side=tk.LEFT)
        self.lbl_status = ttk.Label(status_frame, text="DISCONNECTED", foreground="gray", font=("Helvetica", 10, "bold"))
        self.lbl_status.pack(side=tk.LEFT, padx=5)

        # Buttons
        btn_row = ttk.Frame(ctrl)
        btn_row.pack(fill=tk.X, padx=10, pady=10)
        
        self.btn_latch = ttk.Button(btn_row, text="0. LATCH ZERO", command=self.latch_zero, state="disabled")
        self.btn_latch.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # Step 1: Arm
        self.btn_arm = ttk.Button(btn_row, text="1. ARM SYSTEM (Output ON)", command=self.arm_system, state="disabled")
        self.btn_arm.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # Step 2: Fire
        self.btn_trig = ttk.Button(btn_row, text="2. FIRE 10 CYCLES", command=self.fire_sequence, state="disabled")
        self.btn_trig.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        # Auto-off Checkbox
        self.chk_off = ttk.Checkbutton(ctrl, text="Automatically Turn Output OFF after Burst", variable=self.auto_off_var)
        self.chk_off.pack(pady=(0, 10))

        # --- 4. Log ---
        self.log = scrolledtext.ScrolledText(container, height=10, state=tk.DISABLED)
        self.log.grid(column=0, row=4, columnspan=2, sticky="nsew")
        container.rowconfigure(4, weight=1)

    # --- Logic ---

    def _parse_float(self, val_str, name):
        try:
            # Simple multiplier support
            val_str = val_str.lower().replace(" ", "")
            mult = 1.0
            if val_str.endswith("k"): mult = 1e3
            elif val_str.endswith("m"): mult = 1e6
            elif val_str.endswith("u"): mult = 1e-6
            elif val_str.endswith("n"): mult = 1e-9
            
            clean_val = val_str.strip("kmunhzsv")
            return float(clean_val) * mult
        except:
            raise ValueError(f"Invalid value for {name}")

    def _update_period_hint(self):
        try:
            f = self._parse_float(self.freq_var.get(), "Freq")
            if f > 0:
                p = 1.0/f
                self.period_hint_var.set(f"Period: {p*1000:.2f} ms")
            else:
                self.period_hint_var.set("Period: -")
        except:
            self.period_hint_var.set("Period: -")

    def _update_mode_ui(self):
        if self.run_mode_var.get() == "Burst":
            self.ent_burst.configure(state="normal")
            self.chk_off.configure(state="normal")
            self.btn_trig.configure(text=f"2. FIRE {self.burst_count_var.get()} CYCLES")
        else:
            self.ent_burst.configure(state="disabled")
            self.chk_off.configure(state="disabled")
            self.btn_trig.configure(text="FORCE TRIGGER")

    def connect(self):
        try:
            self.rm = pyvisa.ResourceManager()
            self.inst = self.rm.open_resource(self.addr_var.get(), timeout=5000)
            self.inst.write_termination = "\n"
            idn = self.inst.query("*IDN?").strip()
            self._log(f"Connected to: {idn}")
            
            self.connected = True
            self.btn_connect.config(state="disabled")
            self.btn_disconnect.config(state="normal")
            self.btn_latch.config(state="normal")
            self.btn_arm.config(state="normal")
            self.btn_trig.config(state="normal")
            self.lbl_status.config(text="CONNECTED", foreground="orange")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def disconnect(self):
        if self.inst:
            try:
                self.inst.write("OUTPut1:STATe OFF")
                self.inst.close()
            except: pass
        self.connected = False
        self.output_on = False
        self.latched_zero = False
        self.btn_connect.config(state="normal")
        self.btn_disconnect.config(state="disabled")
        self.btn_arm.config(state="disabled")
        self.btn_trig.config(state="disabled")
        self.btn_latch.config(state="disabled")
        self.lbl_status.config(text="DISCONNECTED", foreground="gray")
        self._log("Disconnected.")

    def latch_zero(self):
        """Program a zero-volt infinite burst that keeps the Sync line low until armed again."""
        if not self.inst:
            return
        try:
            freq = self._parse_float(self.freq_var.get(), "Frequency")
            width = self._parse_float(self.width_var.get(), "Width")
            lead = self._parse_float(self.lead_var.get() or DEFAULT_LEAD, "Rise Time")
            trail = self._parse_float(self.trail_var.get() or DEFAULT_TRAIL, "Fall Time")
            self.inst.write("OUTPut1:STATe OFF")
            self.inst.write("*CLS")
            self.inst.write("SOURce1:FUNCtion:SHAPe PULSe")
            self.inst.write(f"SOURce1:FREQuency:FIXed {freq}")
            self.inst.write(f"SOURce1:PULSe:WIDTh {width}")
            self.inst.write(f"SOURce1:PULSe:TRANsition:LEADing {lead}")
            self.inst.write(f"SOURce1:PULSe:TRANsition:TRAiling {trail}")
            self.inst.write("SOURce1:VOLTage:LEVel:IMMediate:AMPLitude 0")
            self.inst.write("SOURce1:VOLTage:LEVel:IMMediate:OFFSet 0")
            self.inst.write("SOURce1:BURSt:STATe ON")
            self.inst.write("SOURce1:BURSt:MODE TRIGgered")
            self.inst.write("SOURce1:BURSt:NCYCles INFinity")
            self.inst.write("TRIGger:SEQuence:SOURce BUS")
            self.inst.write("OUTPut:TRIGger:MODE SYNC")
            self.latched_zero = True
            self.output_on = False
            self.lbl_status.config(text="LATCHED ZERO", foreground="purple")
            self._log("Latch engaged: channel configured for zero-volt infinite burst. Output remains OFF until you arm/fire.")
        except Exception as e:
            self._log(f"Latch Error: {e}")
            messagebox.showerror("Latch", str(e))

    def _configure_burst_post_latch(self) -> float:
        """Convert the latched infinite-burst profile into the user-selected finite burst."""
        freq = self._parse_float(self.freq_var.get(), "Frequency")
        width = self._parse_float(self.width_var.get(), "Width")
        amp = self._parse_float(self.amp_var.get(), "Amplitude")
        offset = self._parse_float(self.offset_var.get(), "Offset")
        lead = self._parse_float(self.lead_var.get() or DEFAULT_LEAD, "Rise Time")
        trail = self._parse_float(self.trail_var.get() or DEFAULT_TRAIL, "Fall Time")
        delay = self._parse_float(self.delay_var.get() or DEFAULT_DELAY, "Delay")
        load_text = self.load_var.get().strip().upper()
        try:
            cycles = max(1, int(float(self.burst_count_var.get())))
        except ValueError:
            cycles = 1
        self.inst.write("OUTPut1:STATe OFF")
        self.inst.write("*CLS")
        self.inst.write("SOURce1:FUNCtion:SHAPe PULSe")
        self.inst.write(f"SOURce1:FREQuency:FIXed {freq}")
        self.inst.write(f"SOURce1:PULSe:WIDTh {width}")
        self.inst.write(f"SOURce1:PULSe:DELay {delay}")
        self.inst.write(f"SOURce1:PULSe:TRANsition:LEADing {lead}")
        self.inst.write(f"SOURce1:PULSe:TRANsition:TRAiling {trail}")
        if load_text:
            if load_text in {"INF", "INFINITE", "HIGHZ"}:
                self.inst.write("OUTPut1:IMPedance INF")
            else:
                try:
                    load_value = float(load_text)
                    if load_value > 0:
                        self.inst.write(f"OUTPut1:IMPedance {load_value}")
                except ValueError:
                    self._log("Load entry invalid; keeping previous load setting.")
        self.inst.write(f"SOURce1:VOLTage:LEVel:IMMediate:AMPLitude {amp}")
        self.inst.write(f"SOURce1:VOLTage:LEVel:IMMediate:OFFSet {offset}")
        self.inst.write("SOURce1:BURSt:STATe ON")
        self.inst.write("SOURce1:BURSt:MODE TRIGgered")
        self.inst.write(f"SOURce1:BURSt:NCYCles {cycles}")
        self.inst.write("TRIGger:SEQuence:SOURce BUS")
        self.inst.write("OUTPut:TRIGger:MODE SYNC")
        self.latched_zero = False
        self._log(f"Latch released: burst updated to {cycles} cycle(s) with programmed amplitude.")
        return cycles

    def arm_system(self):
        """Applies settings, enables Burst, turns Output ON (Idle 0V)."""
        if not self.inst: return
        try:
            self.latched_zero = False
            # 1. Turn OFF to configure
            self.inst.write("OUTPut1:STATe OFF")
            
            # 2. Get Params
            freq = self._parse_float(self.freq_var.get(), "Frequency")
            width = self._parse_float(self.width_var.get(), "Width")
            amp = self._parse_float(self.amp_var.get(), "Amp")
            offset = self._parse_float(self.offset_var.get(), "Offset")
            cycles = self.burst_count_var.get()
            mode = self.run_mode_var.get()

            # 3. Send SCPI
            self.inst.write("*CLS")
            self.inst.write("SOURce1:FUNCtion:SHAPe PULSe")
            self.inst.write(f"SOURce1:FREQuency:FIXed {freq}")
            self.inst.write(f"SOURce1:PULSe:WIDTh {width}")
            self.inst.write(f"SOURce1:VOLTage:LEVel:IMMediate:AMPLitude {amp}")
            self.inst.write(f"SOURce1:VOLTage:LEVel:IMMediate:OFFSet {offset}")
            
            # --- CRITICAL SYNC/BURST SETTINGS ---
            if mode == "Burst":
                self.inst.write("SOURce1:BURSt:STATe ON")
                self.inst.write("SOURce1:BURSt:MODE TRIGgered")
                self.inst.write(f"SOURce1:BURSt:NCYCles {cycles}")
                
                # Trigger Source = Bus (*TRG)
                self.inst.write("TRIGger:SEQuence:SOURce BUS")
                
                # IMPORTANT: Configure Sync Line (Trigger Out)
                # MODE SYNC means: High during the burst, Low when waiting.
                # This fixes the "Always On" issue.
                self.inst.write("OUTPut:TRIGger:MODE SYNC")
            else:
                self.inst.write("SOURce1:BURSt:STATe OFF")

            # 4. Turn Output ON (Ready to receive trigger)
            self.inst.write("OUTPut1:STATe ON")
            
            self.output_on = True
            self.lbl_status.config(text=f"ARMED ({mode})", foreground="blue")
            self._log(f"System Armed. Mode: {mode}. Cycles: {cycles}")
            self._log("Sync Line is now QUIET (Waiting for Trigger).")

        except Exception as e:
            self._log(f"Error Arming: {e}")
            messagebox.showerror("Error", str(e))

    def fire_sequence(self):
        """Fires *TRG. If Auto-Off is checked, waits for burst to finish then turns OFF."""
        if not self.inst: return
        
        # Run in thread to not freeze UI during sleep
        threading.Thread(target=self._fire_thread).start()

    def _fire_thread(self):
        try:
            if self.latched_zero:
                self._log("Detected latched zero state. Reprogramming burst before firing...")
                cycles = self._configure_burst_post_latch()
            else:
                cycles = float(self.burst_count_var.get())
            freq = self._parse_float(self.freq_var.get(), "Frequency")
            if not self.output_on:
                self.inst.write("OUTPut1:STATe ON")
                self.output_on = True
                self._log("Output turned ON automatically before firing burst.")
            
            # 1. Fire
            self.inst.write("*TRG")
            self._log("Trigger Sent (*TRG) -> Burst Started.")
            
            # 2. Handle Auto-Off
            if self.auto_off_var.get() and self.run_mode_var.get() == "Burst":
                # Calculate duration of burst
                period = 1.0 / freq
                duration = cycles * period
                
                # Add a small buffer (e.g. 50ms) to ensure we don't cut it off too early
                wait_time = duration + 0.1 
                
                self._log(f"Waiting {wait_time:.3f}s for burst to finish...")
                time.sleep(wait_time)
                
                # 3. Turn Output OFF
                self.inst.write("OUTPut1:STATe OFF")
                self.output_on = False
                self._log("Burst Complete. Output set to OFF.")
                
                # Update UI safely
                self.parent.after(0, lambda: self.lbl_status.config(text="OUTPUT OFF", foreground="red"))
            else:
                self._log("Trigger sent. Output remains ON (Idle).")

        except Exception as e:
            self._log(f"Fire Error: {e}")

    def _log(self, msg):
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("AFG3021B Burst Controller")
        self.root.geometry("600x550")
        AFG3021BBurstPanel(self.root)
        self.root.mainloop()

if __name__ == "__main__":
    App()