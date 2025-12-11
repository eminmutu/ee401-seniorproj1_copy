import math
import threading
import time
import tkinter as tk
from tkinter import scrolledtext

import pyvisa

DEFAULT_ADDR = "TCPIP0::169.254.6.24::inst0::INSTR"


class AFG3021BPulseGui:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("AFG3021B Pulse Setup")

        self.rm = None
        self.inst = None
        self.connected = False

        top = tk.Frame(root)
        top.pack(padx=10, pady=8, fill=tk.X)

        tk.Label(top, text="VISA Address:").grid(row=0, column=0, sticky="w")
        self.addr_var = tk.StringVar(value=DEFAULT_ADDR)
        tk.Entry(top, textvariable=self.addr_var, width=45).grid(row=0, column=1, sticky="we", columnspan=3)
        self.btn_connect = tk.Button(top, text="Connect", command=self.on_connect)
        self.btn_connect.grid(row=0, column=4, padx=(6, 0))
        self.btn_disconnect = tk.Button(top, text="Disconnect", command=self.on_disconnect, state="disabled")
        self.btn_disconnect.grid(row=0, column=5, padx=(6, 0))

        tk.Label(top, text="Frequency (Hz):").grid(row=1, column=0, sticky="w")
        self.freq_var = tk.StringVar(value="1000")
        freq_frame = tk.Frame(top)
        freq_frame.grid(row=1, column=1, sticky="w")
        tk.Entry(freq_frame, textvariable=self.freq_var, width=12).pack(side=tk.LEFT)
        self.period_hint_var = tk.StringVar(value="Period: —")
        tk.Label(freq_frame, textvariable=self.period_hint_var).pack(side=tk.LEFT, padx=(8, 0))

        tk.Label(top, text="Pulse width (s):").grid(row=1, column=2, sticky="w")
        self.width_var = tk.StringVar(value="50e-6")
        tk.Entry(top, textvariable=self.width_var, width=12).grid(row=1, column=3, sticky="w")

        tk.Label(top, text="Duty (%)").grid(row=1, column=4, sticky="w")
        self.duty_var = tk.StringVar(value="5.0")
        tk.Entry(top, textvariable=self.duty_var, width=10).grid(row=1, column=5, sticky="w")

        tk.Label(top, text="Hold:").grid(row=1, column=6, sticky="e")
        self.hold_var = tk.StringVar(value="WIDTh")
        tk.OptionMenu(top, self.hold_var, "WIDTh", "DUTY").grid(row=1, column=7, sticky="w")

        tk.Label(top, text="High level (V):").grid(row=2, column=0, sticky="w")
        self.high_var = tk.StringVar(value="1.0")
        tk.Entry(top, textvariable=self.high_var, width=12).grid(row=2, column=1, sticky="w")

        tk.Label(top, text="Low level (V):").grid(row=2, column=2, sticky="w")
        self.low_var = tk.StringVar(value="0.0")
        tk.Entry(top, textvariable=self.low_var, width=12).grid(row=2, column=3, sticky="w")

        tk.Label(top, text="Rise (s):").grid(row=2, column=4, sticky="w")
        self.lead_var = tk.StringVar(value="20e-9")
        tk.Entry(top, textvariable=self.lead_var, width=10).grid(row=2, column=5, sticky="w")

        tk.Label(top, text="Fall (s):").grid(row=2, column=6, sticky="w")
        self.trail_var = tk.StringVar(value="20e-9")
        tk.Entry(top, textvariable=self.trail_var, width=10).grid(row=2, column=7, sticky="w")

        tk.Label(top, text="Load (ohms or INF):").grid(row=3, column=0, sticky="w")
        self.load_var = tk.StringVar(value="INF")
        tk.Entry(top, textvariable=self.load_var, width=12).grid(row=3, column=1, sticky="w")

        tk.Label(top, text="Phase (deg):").grid(row=3, column=2, sticky="w")
        self.phase_var = tk.StringVar(value="0")
        tk.Entry(top, textvariable=self.phase_var, width=12).grid(row=3, column=3, sticky="w")

        top.grid_columnconfigure(1, weight=1)
        top.grid_columnconfigure(3, weight=1)
        top.grid_columnconfigure(5, weight=1)
        top.grid_columnconfigure(7, weight=1)

        btns = tk.Frame(root)
        btns.pack(padx=10, pady=(0, 6), fill=tk.X)
        tk.Button(btns, text="Apply Pulse Setup", command=lambda: self.safe_run(self.apply_pulse)).pack(side=tk.LEFT)
        tk.Button(btns, text="Output ON", command=lambda: self.safe_run(self.output_on)).pack(side=tk.LEFT, padx=6)
        tk.Button(btns, text="Output OFF", command=lambda: self.safe_run(self.output_off)).pack(side=tk.LEFT)
        tk.Button(btns, text="Query", command=lambda: self.safe_run(self.query_status)).pack(side=tk.LEFT, padx=6)
        tk.Button(btns, text="Errors", command=lambda: self.safe_run(self.drain_errors)).pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="Disconnected")
        tk.Label(root, textvariable=self.status_var, anchor="w").pack(padx=10, fill=tk.X)

        self.log = scrolledtext.ScrolledText(root, width=84, height=18, state="disabled")
        self.log.pack(padx=10, pady=(0, 10), fill=tk.BOTH, expand=True)

        try:
            self.freq_var.trace_add("write", lambda *_: self._update_period_hint())
        except Exception:
            self.freq_var.trace("w", lambda *_: self._update_period_hint())
        self._update_period_hint()

    def log_print(self, *args):
        text = " ".join(str(a) for a in args)
        self.log.configure(state="normal")
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)
        self.log.configure(state="disabled")

    def safe_run(self, func):
        thread = threading.Thread(target=self._safe_wrapper, args=(func,))
        thread.daemon = True
        thread.start()

    def _safe_wrapper(self, func):
        try:
            func()
        except Exception as exc:
            self.log_print("Error:", exc)

    def ensure_inst(self):
        if not self.inst:
            raise RuntimeError("Not connected.")

    def on_connect(self):
        addr = self.addr_var.get().strip()
        try:
            if self.rm is None:
                self.rm = pyvisa.ResourceManager()
            if self.inst:
                try:
                    self.inst.close()
                except Exception:
                    pass
            self.inst = self.rm.open_resource(addr)
            self.inst.timeout = 5000
            self.inst.read_termination = "\n"
            self.inst.write_termination = "\n"
            idn = self.inst.query("*IDN?").strip()
            self.log_print("Connected:", idn)
            self.inst.write("*CLS")
            self.inst.write("*RST")
            time.sleep(0.6)
            self.connected = True
            self.status_var.set(f"Connected: {idn}")
            self.btn_connect.configure(state="disabled")
            self.btn_disconnect.configure(state="normal")
        except Exception as exc:
            self.log_print("Connect error:", exc)

    def on_disconnect(self):
        try:
            if self.inst:
                try:
                    self.inst.write("OUTPut1:STATe OFF")
                except Exception:
                    pass
                try:
                    self.inst.close()
                except Exception:
                    pass
            self.inst = None
            self.connected = False
            self.status_var.set("Disconnected")
            self.btn_connect.configure(state="normal")
            self.btn_disconnect.configure(state="disabled")
            self.log_print("Disconnected.")
        finally:
            if self.rm:
                try:
                    self.rm.close()
                except Exception:
                    pass
                self.rm = None

    def apply_pulse(self):
        self.ensure_inst()

        freq = float(self.freq_var.get())
        if freq <= 0:
            raise ValueError("Frequency must be > 0.")
        period = 1.0 / freq

        hold_mode = self.hold_var.get().strip().upper()
        if hold_mode == "WIDTH":
            width = float(self.width_var.get())
            if width <= 0 or width >= period:
                raise ValueError("Width must be > 0 and smaller than the period.")
            duty = 100.0 * width / period
            self.duty_var.set(f"{duty:.6g}")
        else:
            duty = float(self.duty_var.get())
            if duty <= 0 or duty >= 100:
                raise ValueError("Duty cycle must be between 0 and 100%.")
            width = period * duty / 100.0
            if width <= 0 or width >= period:
                raise ValueError("Duty/period combination yields invalid width.")
            self.width_var.set(f"{width:.6g}")
        hold_cmd = "WIDTh" if hold_mode == "WIDTH" else "DUTY"

        high = float(self.high_var.get())
        low = float(self.low_var.get())

        lead = self.lead_var.get().strip()
        trail = self.trail_var.get().strip()
        phase_text = self.phase_var.get().strip()
        load_text = self.load_var.get().strip().upper()

        self.inst.write("OUTPut1:STATe OFF")

        if load_text:
            if load_text in {"INF", "INFINITE", "HIGHZ"}:
                self.inst.write("OUTPut1:IMPedance INF")
            else:
                load_value = float(load_text)
                if load_value <= 0:
                    raise ValueError("Load must be > 0.")
                self.inst.write(f"OUTPut1:IMPedance {load_value}")

        self.inst.write("*CLS")
        self.inst.write("SOURce1:FUNCtion:SHAPe PULSe")
        self.inst.write(f"SOURce1:PULSe:PERiod {period}")
        self.inst.write(f"SOURce1:PULSe:HOLD {hold_cmd}")
        if hold_mode == "WIDTH":
            self.inst.write(f"SOURce1:PULSe:WIDTh {width}")
        else:
            self.inst.write(f"SOURce1:PULSe:DCYCle {duty}")

        self.inst.write(f"SOURce1:VOLTage:LEVel:IMMediate:HIGH {high}")
        self.inst.write(f"SOURce1:VOLTage:LEVel:IMMediate:LOW {low}")

        if lead:
            self.inst.write(f"SOURce1:PULSe:TRANsition:LEADing {lead}")
        if trail:
            self.inst.write(f"SOURce1:PULSe:TRANsition:TRAiling {trail}")
        if phase_text:
            phase = float(phase_text)
            self.inst.write(f"SOURce1:PHASe {phase}")

        self.log_print(f"Pulse applied: {freq} Hz, width {width} s, duty {duty}%")
        self._update_period_hint()

    def output_on(self):
        self.ensure_inst()
        self.inst.write("OUTPut1:STATe ON")
        self.log_print("Output ON")

    def output_off(self):
        self.ensure_inst()
        self.inst.write("OUTPut1:STATe OFF")
        self.log_print("Output OFF")

    def query_status(self):
        self.ensure_inst()
        shape = self.inst.query("SOURce1:FUNCtion:SHAPe?").strip()
        period = self.inst.query("SOURce1:PULSe:PERiod?").strip()
        width = self.inst.query("SOURce1:PULSe:WIDTh?").strip()
        duty = self.inst.query("SOURce1:PULSe:DCYCle?").strip()
        high = self.inst.query("SOURce1:VOLTage:LEVel:IMMediate:HIGH?").strip()
        low = self.inst.query("SOURce1:VOLTage:LEVel:IMMediate:LOW?").strip()
        lead = self.inst.query("SOURce1:PULSe:TRANsition:LEADing?").strip()
        trail = self.inst.query("SOURce1:PULSe:TRANsition:TRAiling?").strip()
        state = self.inst.query("OUTPut1:STATe?").strip()

        self.log_print(f"Shape: {shape}")
        self.log_print(f"Period: {period} s")
        try:
            per_val = float(period)
            if per_val != 0:
                self.log_print(f"Freq : {1.0 / per_val} Hz")
        except Exception:
            pass
        self.log_print(f"Width: {width} s")
        self.log_print(f"Duty : {duty} %")
        self.log_print(f"High : {high} V")
        self.log_print(f"Low  : {low} V")
        self.log_print(f"Rise : {lead} s")
        self.log_print(f"Fall : {trail} s")
        self.log_print(f"Out  : {state}")

    def drain_errors(self):
        self.ensure_inst()
        for _ in range(8):
            err = self.inst.query("SYSTem:ERRor?").strip()
            self.log_print("ERR:", err)
            if err.startswith("0,"):
                break

    @staticmethod
    def _format_seconds_si(seconds: float) -> str:
        try:
            s = float(seconds)
        except Exception:
            return "—"
        if s <= 0 or not math.isfinite(s):
            return "—"
        if s >= 1.0:
            return f"{s:g} s"
        if s >= 1e-3:
            return f"{s*1e3:g} ms"
        if s >= 1e-6:
            return f"{s*1e6:g} µs"
        if s >= 1e-9:
            return f"{s*1e9:g} ns"
        return f"{s*1e12:g} ps"

    def _update_period_hint(self):
        try:
            freq = float(self.freq_var.get())
            if freq > 0:
                period = 1.0 / freq
                self.period_hint_var.set(f"Period ≈ {self._format_seconds_si(period)}")
                return
        except Exception:
            pass
        self.period_hint_var.set("Period: —")


def main():
    root = tk.Tk()
    gui = AFG3021BPulseGui(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (gui.on_disconnect(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
