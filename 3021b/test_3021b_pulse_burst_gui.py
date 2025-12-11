import math
import threading
import time
import tkinter as tk
from tkinter import scrolledtext

import pyvisa

DEFAULT_ADDR = "TCPIP0::169.254.6.24::inst0::INSTR"


class AFG3021BPulseBurstGui:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("AFG3021B Pulse Burst Setup")

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
        self.freq_var = tk.StringVar(value="10000")
        freq_frame = tk.Frame(top)
        freq_frame.grid(row=1, column=1, sticky="w")
        tk.Entry(freq_frame, textvariable=self.freq_var, width=12).pack(side=tk.LEFT)
        self.period_hint_var = tk.StringVar(value="Period: —")
        tk.Label(freq_frame, textvariable=self.period_hint_var).pack(side=tk.LEFT, padx=(8, 0))

        tk.Label(top, text="Pulse width (s):").grid(row=1, column=2, sticky="w")
        self.width_var = tk.StringVar(value="20e-6")
        tk.Entry(top, textvariable=self.width_var, width=12).grid(row=1, column=3, sticky="w")

        tk.Label(top, text="Duty (%)").grid(row=1, column=4, sticky="w")
        self.duty_var = tk.StringVar(value="20.0")
        tk.Entry(top, textvariable=self.duty_var, width=10).grid(row=1, column=5, sticky="w")

        tk.Label(top, text="Hold:").grid(row=1, column=6, sticky="e")
        self.hold_var = tk.StringVar(value="WIDTh")
        tk.OptionMenu(top, self.hold_var, "WIDTh", "DUTY").grid(row=1, column=7, sticky="w")

        tk.Label(top, text="High (V):").grid(row=2, column=0, sticky="w")
        self.high_var = tk.StringVar(value="1.0")
        tk.Entry(top, textvariable=self.high_var, width=12).grid(row=2, column=1, sticky="w")

        tk.Label(top, text="Low (V):").grid(row=2, column=2, sticky="w")
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

        tk.Label(top, text="Burst cycles:").grid(row=4, column=0, sticky="w")
        self.cycles_var = tk.StringVar(value="5")
        tk.Entry(top, textvariable=self.cycles_var, width=12).grid(row=4, column=1, sticky="w")

        tk.Label(top, text="Burst delay (s):").grid(row=4, column=2, sticky="w")
        self.delay_var = tk.StringVar(value="0")
        tk.Entry(top, textvariable=self.delay_var, width=12).grid(row=4, column=3, sticky="w")

        tk.Label(top, text="Burst mode:").grid(row=4, column=4, sticky="e")
        self.burst_mode_var = tk.StringVar(value="TRIGgered")
        tk.OptionMenu(top, self.burst_mode_var, "TRIGgered", "GATed").grid(row=4, column=5, sticky="w")

        tk.Label(top, text="Trigger source:").grid(row=4, column=6, sticky="e")
        self.trig_src_var = tk.StringVar(value="TIMer")
        tk.OptionMenu(top, self.trig_src_var, "TIMer", "EXTernal").grid(row=4, column=7, sticky="w")

        tk.Label(top, text="Trigger period (s):").grid(row=5, column=0, sticky="w")
        self.trig_period_var = tk.StringVar(value="0.05")
        tk.Entry(top, textvariable=self.trig_period_var, width=12).grid(row=5, column=1, sticky="w")

        top.grid_columnconfigure(1, weight=1)
        top.grid_columnconfigure(3, weight=1)
        top.grid_columnconfigure(5, weight=1)
        top.grid_columnconfigure(7, weight=1)

        btns = tk.Frame(root)
        btns.pack(padx=10, pady=(0, 6), fill=tk.X)
        tk.Button(btns, text="Apply Burst Setup", command=lambda: self.safe_run(self.apply_burst)).pack(side=tk.LEFT)
        tk.Button(btns, text="Output ON", command=lambda: self.safe_run(self.output_on)).pack(side=tk.LEFT, padx=6)
        tk.Button(btns, text="Output OFF", command=lambda: self.safe_run(self.output_off)).pack(side=tk.LEFT)
        tk.Button(btns, text="Trigger Now", command=lambda: self.safe_run(self.trigger_now)).pack(side=tk.LEFT, padx=6)
        tk.Button(btns, text="Query", command=lambda: self.safe_run(self.query_status)).pack(side=tk.LEFT)
        tk.Button(btns, text="Errors", command=lambda: self.safe_run(self.drain_errors)).pack(side=tk.LEFT, padx=6)

        self.status_var = tk.StringVar(value="Disconnected")
        tk.Label(root, textvariable=self.status_var, anchor="w").pack(padx=10, fill=tk.X)

        self.log = scrolledtext.ScrolledText(root, width=90, height=18, state="disabled")
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
                    self.inst.write("SOURce1:BURSt:STATe OFF")
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

    def apply_burst(self):
        self.ensure_inst()

        freq = float(self.freq_var.get())
        if freq <= 0:
            raise ValueError("Frequency must be > 0.")
        period = 1.0 / freq

        hold_mode = self.hold_var.get().strip().upper()
        if hold_mode == "WIDTH":
            width = float(self.width_var.get())
            if width <= 0 or width >= period:
                raise ValueError("Width must be > 0 and smaller than period.")
            duty = 100.0 * width / period
            self.duty_var.set(f"{duty:.6g}")
        else:
            duty = float(self.duty_var.get())
            if duty <= 0 or duty >= 100:
                raise ValueError("Duty must be between 0 and 100.")
            width = period * duty / 100.0
            self.width_var.set(f"{width:.6g}")
        hold_cmd = "WIDTh" if hold_mode == "WIDTH" else "DUTY"

        high = float(self.high_var.get())
        low = float(self.low_var.get())

        lead = self.lead_var.get().strip()
        trail = self.trail_var.get().strip()
        phase_text = self.phase_var.get().strip()
        load_text = self.load_var.get().strip().upper()

        cycles = int(float(self.cycles_var.get()))
        if cycles < 1:
            raise ValueError("Burst cycles must be >= 1.")

        delay_s = self._parse_time_to_seconds(self.delay_var.get())
        if delay_s < 0:
            raise ValueError("Burst delay must be >= 0.")

        burst_mode = self.burst_mode_var.get().strip()
        if burst_mode not in {"TRIGgered", "GATed"}:
            raise ValueError("Burst mode must be TRIGgered or GATed.")

        trig_src = self.trig_src_var.get().strip()
        if trig_src not in {"TIMer", "EXTernal"}:
            raise ValueError("Trigger source must be TIMer or EXTernal.")
        trig_period_s = self._parse_time_to_seconds(self.trig_period_var.get())
        if trig_src == "TIMer" and trig_period_s <= 0:
            raise ValueError("Trigger period must be > 0 for TIMer source.")

        self.inst.write("OUTPut1:STATe OFF")

        if load_text:
            if load_text in {"INF", "INFINITE", "HIGHZ"}:
                self.inst.write("OUTPut1:IMPedance INF")
            else:
                load_val = float(load_text)
                if load_val <= 0:
                    raise ValueError("Load must be > 0.")
                self.inst.write(f"OUTPut1:IMPedance {load_val}")

        self.inst.write("*CLS")
        self.inst.write("SOURce1:FUNCtion:SHAPe PULSe")
        self.inst.write(f"SOURce1:PULSe:PERiod {period}")
        self.inst.write(f"SOURce1:PULSe:HOLD {hold_cmd}")
        if hold_cmd == "WIDTh":
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

        self.inst.write(f"SOURce1:BURSt:MODE {burst_mode}")
        self.inst.write(f"SOURce1:BURSt:NCYCles {cycles}")
        if burst_mode.upper().startswith("TRIG"):
            self.inst.write(f"SOURce1:BURSt:TDELay {delay_s}")
        self.inst.write("SOURce1:BURSt:STATe ON")

        self.inst.write(f"TRIGger:SEQuence:SOURce {trig_src}")
        if trig_src == "TIMer":
            self.inst.write(f"TRIGger:SEQuence:TIMer {trig_period_s}")

        self.log_print(
            f"Burst applied: {freq} Hz, width {width} s, duty {duty} %, cycles {cycles}, mode {burst_mode}, trig {trig_src}"
        )
        self._update_period_hint()

    def output_on(self):
        self.ensure_inst()
        self.inst.write("OUTPut1:STATe ON")
        self.log_print("Output ON")

    def output_off(self):
        self.ensure_inst()
        self.inst.write("OUTPut1:STATe OFF")
        self.log_print("Output OFF")

    def trigger_now(self):
        self.ensure_inst()
        self.inst.write("TRIGger:SEQuence:IMMediate")
        self.log_print("Manual trigger sent.")

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
        burst_mode = self.inst.query("SOURce1:BURSt:MODE?").strip()
        burst_state = self.inst.query("SOURce1:BURSt:STATe?").strip()
        cycles = self.inst.query("SOURce1:BURSt:NCYCles?").strip()
        delay = None
        if burst_mode.upper().startswith("TRIG"):
            try:
                delay = self.inst.query("SOURce1:BURSt:TDELay?").strip()
            except Exception as exc:
                delay = f"Error: {exc}"
        trig_src = self.inst.query("TRIGger:SEQuence:SOURce?").strip()
        out_state = self.inst.query("OUTPut1:STATe?").strip()

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
        self.log_print(f"Burst mode : {burst_mode}")
        self.log_print(f"Burst state: {burst_state}")
        self.log_print(f"Burst cycles: {cycles}")
        if delay is not None:
            self.log_print(f"Burst delay : {delay} s")
        self.log_print(f"Trigger src: {trig_src}")
        if trig_src.upper().startswith("TIM"):
            try:
                trig_period = self.inst.query("TRIGger:SEQuence:TIMer?").strip()
                self.log_print(f"Trigger period: {trig_period} s")
            except Exception as exc:
                self.log_print("Trigger period query error:", exc)
        self.log_print(f"Output: {out_state}")

    def drain_errors(self):
        self.ensure_inst()
        for _ in range(8):
            err = self.inst.query("SYSTem:ERRor?").strip()
            self.log_print("ERR:", err)
            if err.startswith("0,"):
                break

    @staticmethod
    def _parse_time_to_seconds(text: str) -> float:
        t = text.strip().lower().replace(" ", "")
        if not t:
            raise ValueError("Empty time value.")
        units = {
            "s": 1.0,
            "ms": 1e-3,
            "us": 1e-6,
            "µs": 1e-6,
            "ns": 1e-9,
            "ps": 1e-12,
        }
        for u in sorted(units.keys(), key=len, reverse=True):
            if t.endswith(u):
                return float(t[: -len(u)]) * units[u]
        return float(t)

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
    gui = AFG3021BPulseBurstGui(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (gui.on_disconnect(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
