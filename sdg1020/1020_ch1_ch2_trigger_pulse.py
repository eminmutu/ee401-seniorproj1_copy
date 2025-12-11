"""
SDG1020 Dual Channel - Manual Trigger Fix
- Logic: Waveform -> Width/Duty -> Burst State ON -> Set Manual Trigger.
- Removed: Burst Period (Invalid in Manual Mode).
- Fire Sequence: Preserved exactly as requested (MTRIG commands).
"""

import threading
import tkinter as tk
from tkinter import scrolledtext, messagebox, ttk
import pyvisa
import time

# VISA Address
DEFAULT_ADDR = "USB0::0xF4ED::0xEE3A::NDG10GA1160419::INSTR"

# --- User Defaults ---
DEF_PULSE_PER = "1e-6"    # 1 us
DEF_PULSE_WID = "0.5e-6"  # 0.5 us
DEF_AMP       = "2.0"     # 2.0 Vpp
DEF_BURST_DLY = "50e-6"   # 50 us

class SDG1020DualGui:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("SDG1020 - Manual Trigger Setup Fix")
        self.root.geometry("650x900")

        self.rm = None
        self.inst = None

        # --- Connection ---
        conn_frame = ttk.LabelFrame(root, text="Connection")
        conn_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(conn_frame, text="VISA Address:").pack(side=tk.LEFT, padx=5)
        self.addr_var = tk.StringVar(value=DEFAULT_ADDR)
        ttk.Entry(conn_frame, textvariable=self.addr_var, width=40).pack(side=tk.LEFT, padx=5)
        
        self.btn_connect = ttk.Button(conn_frame, text="Connect", command=self.safe_run(self.connect))
        self.btn_connect.pack(side=tk.LEFT, padx=5)
        self.btn_disconnect = ttk.Button(conn_frame, text="Disconnect", state="disabled", command=self.safe_run(self.disconnect))
        self.btn_disconnect.pack(side=tk.LEFT)

        # --- CH1: MAIN SIGNAL ---
        ch1_frame = ttk.LabelFrame(root, text="CH1: Signal (5 Pulses)")
        ch1_frame.pack(fill=tk.X, padx=10, pady=5)

        self.ch1_period = self.create_param(ch1_frame, "Pulse Period (s):", DEF_PULSE_PER, 0, 0)
        self.ch1_width  = self.create_param(ch1_frame, "Pulse Width (s):", DEF_PULSE_WID, 0, 2)
        self.ch1_amp    = self.create_param(ch1_frame, "Amp (Vpp):", DEF_AMP, 1, 0)
        self.ch1_cycles = self.create_param(ch1_frame, "Burst Cycles:", "5", 1, 2)
        # Removed Burst Period field
        self.ch1_b_delay = self.create_param(ch1_frame, "Burst Delay (s):", DEF_BURST_DLY, 2, 2)

        # --- CH2: TRIGGER ---
        ch2_frame = ttk.LabelFrame(root, text="CH2: Trigger (1 Pulse)")
        ch2_frame.pack(fill=tk.X, padx=10, pady=5)

        self.ch2_period = self.create_param(ch2_frame, "Pulse Period (s):", DEF_PULSE_PER, 0, 0)
        self.ch2_width  = self.create_param(ch2_frame, "Pulse Width (s):", DEF_PULSE_WID, 0, 2)
        self.ch2_amp    = self.create_param(ch2_frame, "Amp (Vpp):", DEF_AMP, 1, 0)
        self.ch2_cycles = self.create_param(ch2_frame, "Burst Cycles:", "1", 1, 2)
        # Removed Burst Period field
        self.ch2_b_delay = self.create_param(ch2_frame, "Burst Delay (s):", DEF_BURST_DLY, 2, 2)

        # --- CONTROL CENTER ---
        ctrl_frame = ttk.LabelFrame(root, text="Control Center")
        ctrl_frame.pack(fill=tk.X, padx=10, pady=10)

        # Split Configuration Buttons
        btn_row = ttk.Frame(ctrl_frame)
        btn_row.pack(fill=tk.X, padx=5, pady=5)
        
        self.btn_set_ch1 = ttk.Button(btn_row, text="1. Set CH1 Only", command=self.safe_run(self.apply_ch1))
        self.btn_set_ch1.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        self.btn_set_ch2 = ttk.Button(btn_row, text="2. Set CH2 Only", command=self.safe_run(self.apply_ch2))
        self.btn_set_ch2.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # Fire Button
        self.btn_fire = tk.Button(ctrl_frame, text="3. FIRE DUAL BURST", bg="#ffcccc", height=2, font=("Arial", 11, "bold"),
                                  command=self.safe_run(self.fire_sequence))
        self.btn_fire.pack(fill=tk.X, padx=10, pady=5)

        # Stop Button
        ttk.Button(ctrl_frame, text="Emergency Output OFF", command=self.safe_run(self.all_off)).pack(fill=tk.X, padx=10, pady=5)

        # Log
        self.log = scrolledtext.ScrolledText(root, height=12, state="disabled")
        self.log.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

    def create_param(self, parent, label, default, r, c):
        ttk.Label(parent, text=label).grid(row=r, column=c, sticky="e", padx=5, pady=2)
        var = tk.StringVar(value=default)
        ttk.Entry(parent, textvariable=var, width=12).grid(row=r, column=c+1, sticky="w", padx=5, pady=2)
        return var

    def write_inst(self, cmd):
        if self.inst:
            self.inst.write(cmd)
            time.sleep(0.05) 
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

    def connect(self):
        try:
            self.rm = pyvisa.ResourceManager()
            self.inst = self.rm.open_resource(self.addr_var.get())
            self.inst.timeout = 5000
            idn = self.inst.query("*IDN?").strip()
            self.log_message(f"Connected: {idn}")
            self.btn_connect.config(state="disabled")
            self.btn_disconnect.config(state="normal")
        except Exception as e:
            messagebox.showerror("Connection Error", str(e))

    def disconnect(self):
        self.all_off()
        if self.inst: self.inst.close()
        self.btn_connect.config(state="normal")
        self.btn_disconnect.config(state="disabled")

    def all_off(self):
        if self.inst:
            self.write_inst("C1:OUTP OFF")
            self.write_inst("C2:OUTP OFF")
            self.log_message("All Outputs OFF")

    def parse(self, v):
        val = v.get().lower().replace('us','e-6').replace('ms','e-3').replace('ns','e-9')
        return float(val)

    # --- SEPARATE CONFIGURATION FUNCTIONS ---

    def apply_ch1(self):
        """Configures Channel 1 Only"""
        if not self.inst: return
        self._configure_channel(1, self.ch1_period, self.ch1_width, self.ch1_amp, 
                                self.ch1_cycles, self.ch1_b_delay)
        self.log_message("CH1 Configured & Armed (Output ON, Waiting for Trig)")

    def apply_ch2(self):
        """Configures Channel 2 Only"""
        if not self.inst: return
        self._configure_channel(2, self.ch2_period, self.ch2_width, self.ch2_amp, 
                                self.ch2_cycles, self.ch2_b_delay)
        self.log_message("CH2 Configured & Armed (Output ON, Waiting for Trig)")

    def _configure_channel(self, ch, period_v, width_v, amp_v, cycles_v, b_delay_v):
        """Helper to configure a single channel"""
        p = self.parse(period_v)
        w = self.parse(width_v)
        amp = amp_v.get()
        bd = self.parse(b_delay_v)
        
        # Calculate Duty Cycle
        duty = (w / p) * 100.0
        
        # 1. Reset State
        self.write_inst(f"C{ch}:OUTP OFF")
        #elf.write_inst(f"C{ch}:BTWV STATE,OFF")
        
        # 2. Configure Waveform
        # Force Pulse Mode with valid Duty Cycle
        cmd_wave = f"C{ch}:BSWV WVTP,PULSE,PERI,{p:.9g},AMP,{amp},DUTY,{duty:.4f},OFST,0"
        self.write_inst(cmd_wave)
        
        # 3. Enable Burst State FIRST
        # This is the key fix: Turn State ON before setting Manual Source
        self.write_inst(f"C{ch}:BTWV STATE,ON")
        
        # 4. Configure Burst Parameters (MANUAL TRIGGER)
        # Note: PRD (Period) command removed as requested
        
        self.write_inst(f"C{ch}:BTWV GATE_NCYC,NCYC")
        self.write_inst(f"C{ch}:BTWV TIME,{cycles_v.get()}")
        self.write_inst("*WAI")
        self.write_inst(f"C{ch}:BTWV DLAY,{bd:.9g}")
        self.write_inst(f"C{ch}:BTWV TRSR,MAN") 
        
        # 5. Turn Output ON (Ready to receive MTRIG)
        self.inst.write(f"C{ch}:OUTP ON")

    def fire_sequence(self):
        """
        Fires both channels: MTRIG commands only (Outputs already ON from config)
        """
        if not self.inst: return

        self.log_message(">>> FIRING...")

        # No need to turn outputs ON here, they were turned ON in config step.
        
        self.write_inst("C1:BTWV MTRIG")
        self.write_inst("C2:BTWV MTRIG")

if __name__ == "__main__":
    root = tk.Tk()
    app = SDG1020DualGui(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.disconnect(), root.destroy()))
    root.mainloop()