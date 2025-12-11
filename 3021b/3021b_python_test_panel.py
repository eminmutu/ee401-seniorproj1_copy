from __future__ import annotations

import tkinter as tk
from tkinter import scrolledtext, ttk, messagebox
from typing import Dict, List

import pyvisa

DEFAULT_ADDRESS = "TCPIP0::169.254.6.24::inst0::INSTR"
DEFAULT_PULSE_FREQ = "1000"
DEFAULT_PULSE_WIDTH = "50e-6"
DEFAULT_PULSE_DUTY = "5.0"
DEFAULT_PULSE_HIGH = "1.0"
DEFAULT_PULSE_LOW = "0.0"
DEFAULT_PULSE_LEAD = "20e-9"
DEFAULT_PULSE_TRAIL = "20e-9"
DEFAULT_PULSE_LOAD = "INF"
DEFAULT_PULSE_PHASE = "0"

BURST_RECIPES: Dict[str, List[str]] = {
    "SYNC mode (Trigger Out pulse on first trigger)": [ #this turns ttl off #best option right now but needs tweaking
        "*RST",
        "*CLS",
        "SOUR1:FUNC PULSE",
        "SOUR1:FREQ 1e3",
        "SOUR1:VOLT 1",
        "OUTP1 ON", 
        "SOUR1:BURS:STAT ON",
        "SOUR1:BURS:MODE TRIG",
        "SOUR1:BURS:NCYC INF",
        "OUTP:TRIG:MODE SYNC",
        "TRIG:SEQ:SOUR IMM",
        "TRIG:SEQ:IMM",
    ],
    "TRIG mode (Trigger Out behavior in TRIG)": [ #this turns ttl off
        "*RST",
        "*CLS",
        "SOUR1:FUNC PULSE",
        "SOUR1:FREQ 1e3",
        "SOUR1:VOLT 1",
        "SOUR1:BURS:STAT ON",
        "SOUR1:BURS:MODE TRIG",
        "SOUR1:BURS:NCYC INF",
        "OUTP:TRIG:MODE TRIG",
        "TRIG:SEQ:SOUR IMM",
        "TRIG:SEQ:IMM",
    ],
    "Infinite burst sine (SYNC pulse at start)": [
        "*RST",
        "*CLS",
        "SOUR1:FUNC SIN",
        "SOUR1:FREQ 1E6",
        "SOUR1:VOLT 1",
        "OUTP1 ON",
        "SOUR1:BURS:STAT ON",
        "SOUR1:BURS:MODE TRIG",
        "SOUR1:BURS:NCYC INF",
        "OUTP:TRIG:MODE SYNC",
        "TRIG:SEQ:SOUR IMM",
        "TRIG:SEQ:IMM",
    ],
    "Finite 5-cycle burst via *TRG": [
        "*RST",
        "*CLS",
        "SOUR1:FUNC PULSE",
        "SOUR1:FREQ 10E3",
        "SOUR1:VOLT 2",
        "SOUR1:BURS:STAT ON",
        "SOUR1:BURS:MODE TRIG",
        "SOUR1:BURS:NCYC 5",
        "OUTP1 ON",
        "OUTP:TRIG:MODE TRIG",
        "TRIG:SEQ:SOUR BUS",
        "*TRG",
    ],
    "500 Hz 10-cycle burst with SYNC pulse": [
        "*RST",
        "*CLS",
        "SOUR1:FUNC PULSE",
        "SOUR1:FREQ 500",
        "SOUR1:VOLT 2",
        "SOUR1:PULS:DCYC 50",
        "SOUR1:BURS:STAT ON",
        "SOUR1:BURS:MODE TRIG",
        "SOUR1:BURS:NCYC 10",
        "TRIG:SEQ:SOUR BUS",
        "OUTP:TRIG:MODE SYNC",
        "OUTP1 ON",
        "*TRG",
        "OUTP1 OFF",
    ],
    "10 MHz 5-cycle burst with SYNC pulse": [
        "*RST",
        "*CLS",
        "SOUR1:FUNC PULSE",
        "SOUR1:FREQ 10E6",
        "SOUR1:PULS:DCYC 50",
        "SOUR1:VOLT 1.0",
        "SOUR1:BURS:STAT ON",
        "SOUR1:BURS:MODE TRIG",
        "SOUR1:BURS:NCYC 5",
        "TRIG:SEQ:SOUR BUS",
        "OUTP:TRIG:MODE SYNC",
        "OUTP1 ON",
        "*TRG",
    ],
    "5 MHz 10-cycle burst with SYNC pulse": [
        "*RST",
        "*CLS",
        "SOUR1:FUNC PULSE",
        "SOUR1:FREQ 5E6",
        "SOUR1:PULS:DCYC 50",
        "SOUR1:VOLT 1.0",
        "SOUR1:BURS:STAT ON",
        "SOUR1:BURS:MODE TRIG",
        "SOUR1:BURS:NCYC 10",
        "TRIG:SEQ:SOUR BUS",
        "OUTP:TRIG:MODE SYNC",
        "OUTP1 ON",
        "*TRG",
    ],
    "5 MHz single-cycle burst (bus trigger)": [
        "*RST",
        "*CLS",
        "SOUR1:FUNC PULSE",
        "SOUR1:FREQ 5E6",
        "SOUR1:PULS:DCYC 50",
        "SOUR1:VOLT 1.0",
        "SOUR1:BURS:STAT ON",
        "SOUR1:BURS:MODE TRIG",
        "SOUR1:BURS:NCYC 1",
        "TRIG:SEQ:SOUR BUS",
        "OUTP:TRIG:MODE SYNC",
        "OUTP1 ON",
        "*TRG",
        "OUTP1 OFF",
        "SOUR1:BURS:STAT OFF",
    ],
}


class VisaConsoleApp:
    """Minimal SCPI console backed by PyVISA."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("3021B SCPI Console")
        self.rm: pyvisa.ResourceManager | None = None
        self.inst: pyvisa.resources.MessageBasedResource | None = None

        self.address_var = tk.StringVar(value=DEFAULT_ADDRESS)
        self.cmd_var = tk.StringVar(value="*IDN?")
        self.timeout_var = tk.StringVar(value="5000")
        self.freq_var = tk.StringVar(value=DEFAULT_PULSE_FREQ)
        self.width_var = tk.StringVar(value=DEFAULT_PULSE_WIDTH)
        self.duty_var = tk.StringVar(value=DEFAULT_PULSE_DUTY)
        self.high_var = tk.StringVar(value=DEFAULT_PULSE_HIGH)
        self.low_var = tk.StringVar(value=DEFAULT_PULSE_LOW)
        self.lead_var = tk.StringVar(value=DEFAULT_PULSE_LEAD)
        self.trail_var = tk.StringVar(value=DEFAULT_PULSE_TRAIL)
        self.load_var = tk.StringVar(value=DEFAULT_PULSE_LOAD)
        self.phase_var = tk.StringVar(value=DEFAULT_PULSE_PHASE)
        self.hold_var = tk.StringVar(value="WIDTh")
        self.period_hint_var = tk.StringVar(value="Period: —")

        self._build_ui()
        try:
            self.freq_var.trace_add("write", lambda *_: self._update_period_hint())
        except AttributeError:
            self.freq_var.trace("w", lambda *_: self._update_period_hint())
        self._update_period_hint()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=12)
        top.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="VISA address:").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.address_var).grid(
            row=0, column=1, sticky="ew", padx=(6, 6)
        )

        ttk.Label(top, text="Timeout (ms):").grid(row=0, column=2, sticky="w")
        ttk.Entry(top, textvariable=self.timeout_var, width=8).grid(row=0, column=3, sticky="ew")

        self.btn_connect = ttk.Button(top, text="Connect", command=self.connect)
        self.btn_connect.grid(row=0, column=4, padx=(6, 0))
        self.btn_disconnect = ttk.Button(top, text="Disconnect", command=self.disconnect, state=tk.DISABLED)
        self.btn_disconnect.grid(row=0, column=5, padx=(6, 0))

        ttk.Label(top, text="SCPI Command:").grid(row=1, column=0, sticky="w", pady=(12, 0))
        cmd_entry = ttk.Entry(top, textvariable=self.cmd_var)
        cmd_entry.grid(row=1, column=1, columnspan=4, sticky="ew", padx=(6, 6), pady=(12, 0))
        cmd_entry.bind("<Return>", lambda _event: self.write_command())

        btn_frame = ttk.Frame(top)
        btn_frame.grid(row=1, column=5, sticky="e", pady=(12, 0))
        ttk.Button(btn_frame, text="Write", command=self.write_command).grid(row=0, column=0, padx=2)
        ttk.Button(btn_frame, text="Query", command=self.query_command).grid(row=0, column=1, padx=2)
        ttk.Button(btn_frame, text="Read", command=self.read_only).grid(row=0, column=2, padx=2)

        ttk.Label(top, text="Console:").grid(row=2, column=0, sticky="w", pady=(12, 0))
        self.console = scrolledtext.ScrolledText(top, height=16, state=tk.DISABLED)
        self.console.grid(row=3, column=0, columnspan=6, sticky="nsew", pady=(4, 0))
        top.rowconfigure(3, weight=1)

        pulse_frame = ttk.LabelFrame(top, text="Pulse Configuration (Channel 1)")
        pulse_frame.grid(row=4, column=0, columnspan=6, sticky="ew", pady=(12, 0))
        for col in range(8):
            if col % 2 == 1:
                pulse_frame.columnconfigure(col, weight=1)

        ttk.Label(pulse_frame, text="Frequency (Hz)").grid(row=0, column=0, sticky="w", padx=(6, 0))
        freq_wrap = ttk.Frame(pulse_frame)
        freq_wrap.grid(row=0, column=1, sticky="we", padx=(4, 10))
        ttk.Entry(freq_wrap, textvariable=self.freq_var, width=14).pack(side=tk.LEFT)
        ttk.Label(freq_wrap, textvariable=self.period_hint_var).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(pulse_frame, text="Pulse width (s)").grid(row=0, column=2, sticky="w")
        ttk.Entry(pulse_frame, textvariable=self.width_var, width=14).grid(row=0, column=3, sticky="w", padx=(4, 10))

        ttk.Label(pulse_frame, text="Duty (%)").grid(row=0, column=4, sticky="w")
        ttk.Entry(pulse_frame, textvariable=self.duty_var, width=12).grid(row=0, column=5, sticky="w", padx=(4, 10))

        ttk.Label(pulse_frame, text="Hold").grid(row=0, column=6, sticky="e")
        ttk.Combobox(
            pulse_frame,
            textvariable=self.hold_var,
            values=("WIDTh", "DUTY"),
            width=8,
            state="readonly",
        ).grid(row=0, column=7, sticky="w")

        ttk.Label(pulse_frame, text="High level (V)").grid(row=1, column=0, sticky="w", padx=(6, 0), pady=(6, 0))
        ttk.Entry(pulse_frame, textvariable=self.high_var, width=14).grid(row=1, column=1, sticky="w", padx=(4, 10), pady=(6, 0))

        ttk.Label(pulse_frame, text="Low level (V)").grid(row=1, column=2, sticky="w", pady=(6, 0))
        ttk.Entry(pulse_frame, textvariable=self.low_var, width=14).grid(row=1, column=3, sticky="w", padx=(4, 10), pady=(6, 0))

        ttk.Label(pulse_frame, text="Rise (s)").grid(row=1, column=4, sticky="w", pady=(6, 0))
        ttk.Entry(pulse_frame, textvariable=self.lead_var, width=12).grid(row=1, column=5, sticky="w", padx=(4, 10), pady=(6, 0))

        ttk.Label(pulse_frame, text="Fall (s)").grid(row=1, column=6, sticky="w", pady=(6, 0))
        ttk.Entry(pulse_frame, textvariable=self.trail_var, width=12).grid(row=1, column=7, sticky="w", pady=(6, 0))

        ttk.Label(pulse_frame, text="Load (Ω or INF)").grid(row=2, column=0, sticky="w", padx=(6, 0), pady=(6, 0))
        ttk.Entry(pulse_frame, textvariable=self.load_var, width=14).grid(row=2, column=1, sticky="w", padx=(4, 10), pady=(6, 0))

        ttk.Label(pulse_frame, text="Phase (deg)").grid(row=2, column=2, sticky="w", pady=(6, 0))
        ttk.Entry(pulse_frame, textvariable=self.phase_var, width=14).grid(row=2, column=3, sticky="w", padx=(4, 10), pady=(6, 0))

        pulse_btns = ttk.Frame(pulse_frame)
        pulse_btns.grid(row=3, column=0, columnspan=8, sticky="ew", pady=(8, 0))
        pulse_btns.columnconfigure((0, 1, 2, 3), weight=1)
        ttk.Button(pulse_btns, text="Apply Pulse Setup", command=self.apply_pulse).grid(row=0, column=0, padx=4)
        ttk.Button(pulse_btns, text="Output ON", command=self.output_on).grid(row=0, column=1, padx=4)
        ttk.Button(pulse_btns, text="Output OFF", command=self.output_off).grid(row=0, column=2, padx=4)
        ttk.Button(pulse_btns, text="Query", command=self.query_pulse).grid(row=0, column=3, padx=4)
        ttk.Button(pulse_btns, text="Errors", command=self.drain_errors).grid(row=0, column=4, padx=4)

        recipe_frame = ttk.LabelFrame(top, text="Burst Behavior Demos")
        recipe_frame.grid(row=5, column=0, columnspan=6, sticky="ew", pady=(12, 0))
        recipe_frame.columnconfigure(1, weight=1)
        ttk.Label(recipe_frame, text="Recipe:").grid(row=0, column=0, sticky="w", padx=(6, 0))
        self.recipe_var = tk.StringVar(value=list(BURST_RECIPES.keys())[0])
        ttk.Combobox(
            recipe_frame,
            textvariable=self.recipe_var,
            values=list(BURST_RECIPES.keys()),
            state="readonly",
            width=40,
        ).grid(row=0, column=1, sticky="ew", padx=6, pady=6)
        ttk.Button(recipe_frame, text="Run Recipe", command=self.run_selected_recipe).grid(
            row=0, column=2, padx=6, pady=6
        )

        clear_frame = ttk.Frame(top)
        clear_frame.grid(row=6, column=0, columnspan=6, sticky="ew", pady=(8, 0))
        ttk.Button(clear_frame, text="Clear Console", command=self.clear_console).pack(side=tk.RIGHT)

    # -------------------------- Instrument control --------------------------
    def connect(self) -> None:
        address = self.address_var.get().strip()
        timeout = self._parse_timeout()
        if not address:
            messagebox.showerror("Connect", "Please enter a VISA address.")
            return
        try:
            if self.rm is None:
                self.rm = pyvisa.ResourceManager()
            self.inst = self.rm.open_resource(address)
            self.inst.timeout = timeout
            self.inst.read_termination = "\n"
            self.inst.write_termination = "\n"
            idn = self.inst.query("*IDN?").strip()
            self._log(f"Connected to {idn}")
            self.btn_connect.configure(state=tk.DISABLED)
            self.btn_disconnect.configure(state=tk.NORMAL)
        except pyvisa.VisaIOError as error:
            self._log(f"Connection failed: {error}")
            messagebox.showerror("Connect", str(error))
            self.inst = None

    def disconnect(self) -> None:
        if self.inst:
            try:
                self.inst.close()
            except pyvisa.VisaIOError:
                pass
            self.inst = None
        if self.rm:
            try:
                self.rm.close()
            except pyvisa.VisaIOError:
                pass
            self.rm = None
        self._log("Disconnected.")
        self.btn_connect.configure(state=tk.NORMAL)
        self.btn_disconnect.configure(state=tk.DISABLED)

    # ------------------------------- Commands --------------------------------
    def write_command(self) -> None:
        cmd = self.cmd_var.get().strip()
        if not cmd:
            return
        if not self._check_connection():
            return
        try:
            self.inst.write(cmd)
            self._log(f"> {cmd}")
        except pyvisa.VisaIOError as error:
            self._log(f"Write error: {error}")

    def query_command(self) -> None:
        cmd = self.cmd_var.get().strip()
        if not cmd:
            return
        if not self._check_connection():
            return
        try:
            response = self.inst.query(cmd).strip()
        except pyvisa.VisaIOError as error:
            self._log(f"Query error: {error}")
            return
        self._log(f"> {cmd}")
        self._log(f"< {response}")

    def read_only(self) -> None:
        if not self._check_connection():
            return
        try:
            response = self.inst.read().strip()
            self._log(f"< {response}")
        except pyvisa.VisaIOError as error:
            self._log(f"Read error: {error}")

    # ----------------------------- Utilities --------------------------------
    def _parse_timeout(self) -> int:
        value = self.timeout_var.get().strip()
        try:
            timeout = int(float(value))
        except ValueError:
            timeout = 5000
            self.timeout_var.set(str(timeout))
        return max(timeout, 100)

    def _check_connection(self) -> bool:
        if self.inst is None:
            messagebox.showwarning("Instrument", "Connect to the instrument first.")
            return False
        return True

    def _log(self, message: str) -> None:
        self.console.configure(state=tk.NORMAL)
        self.console.insert(tk.END, message + "\n")
        self.console.see(tk.END)
        self.console.configure(state=tk.DISABLED)

    def clear_console(self) -> None:
        self.console.configure(state=tk.NORMAL)
        self.console.delete("1.0", tk.END)
        self.console.configure(state=tk.DISABLED)

    def run_selected_recipe(self) -> None:
        if not self._check_connection():
            return
        recipe_name = self.recipe_var.get()
        steps = BURST_RECIPES.get(recipe_name)
        if not steps:
            messagebox.showerror("Recipe", f"Recipe '{recipe_name}' is undefined.")
            return
        self._log(f"[Recipe] Running '{recipe_name}'")
        for cmd in steps:
            try:
                self.inst.write(cmd)
                self._log(f"> {cmd}")
            except pyvisa.VisaIOError as error:
                self._log(f"[Recipe] Aborted on '{cmd}': {error}")
                return
        self._log(f"[Recipe] Completed '{recipe_name}'")

    # -------------------------- Pulse configuration ------------------------
    def apply_pulse(self) -> None:
        if not self._check_connection():
            return
        try:
            freq = float(self.freq_var.get())
            width_entry = float(self.width_var.get())
            duty_entry = float(self.duty_var.get())
            high = float(self.high_var.get())
            low = float(self.low_var.get())
        except ValueError as exc:
            messagebox.showerror("Pulse", f"Invalid numeric entry: {exc}")
            return
        if freq <= 0:
            messagebox.showerror("Pulse", "Frequency must be > 0.")
            return
        period = 1.0 / freq
        hold_mode = self.hold_var.get().strip().upper()
        if hold_mode not in {"WIDTH", "DUTY"}:
            hold_mode = "WIDTH"
            self.hold_var.set("WIDTh")
        if hold_mode == "WIDTH":
            width = width_entry
            if width <= 0 or width >= period:
                messagebox.showerror("Pulse", "Width must be between 0 and the period.")
                return
            duty = 100.0 * width / period
            self.duty_var.set(f"{duty:.6g}")
        else:
            duty = duty_entry
            if not 0 < duty < 100:
                messagebox.showerror("Pulse", "Duty cycle must be between 0 and 100%.")
                return
            width = period * duty / 100.0
            if width <= 0 or width >= period:
                messagebox.showerror("Pulse", "Duty/period combination yields invalid width.")
                return
            self.width_var.set(f"{width:.6g}")
        load_text = self.load_var.get().strip().upper()
        lead = self.lead_var.get().strip()
        trail = self.trail_var.get().strip()
        phase_txt = self.phase_var.get().strip()

        try:
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
            hold_cmd = "WIDTh" if hold_mode == "WIDTH" else "DUTY"
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
            if phase_txt:
                phase = float(phase_txt)
                self.inst.write(f"SOURce1:PHASe {phase}")
        except ValueError as exc:
            messagebox.showerror("Pulse", str(exc))
            return
        except pyvisa.VisaIOError as exc:
            self._log(f"Pulse configure error: {exc}")
            messagebox.showerror("Pulse", str(exc))
            return
        self._log(
            f"Pulse applied: freq={freq} Hz, width={width} s, duty={duty}%, high={high} V, low={low} V"
        )
        self._update_period_hint()

    def output_on(self) -> None:
        if not self._check_connection():
            return
        try:
            self.inst.write("OUTPut1:STATe ON")
            self._log("Output ON")
        except pyvisa.VisaIOError as exc:
            self._log(f"Output ON failed: {exc}")

    def output_off(self) -> None:
        if not self._check_connection():
            return
        try:
            self.inst.write("OUTPut1:STATe OFF")
            self._log("Output OFF")
        except pyvisa.VisaIOError as exc:
            self._log(f"Output OFF failed: {exc}")

    def query_pulse(self) -> None:
        if not self._check_connection():
            return
        try:
            shape = self.inst.query("SOURce1:FUNCtion:SHAPe?").strip()
            period = self.inst.query("SOURce1:PULSe:PERiod?").strip()
            width = self.inst.query("SOURce1:PULSe:WIDTh?").strip()
            duty = self.inst.query("SOURce1:PULSe:DCYCle?").strip()
            high = self.inst.query("SOURce1:VOLTage:LEVel:IMMediate:HIGH?").strip()
            low = self.inst.query("SOURce1:VOLTage:LEVel:IMMediate:LOW?").strip()
            lead = self.inst.query("SOURce1:PULSe:TRANsition:LEADing?").strip()
            trail = self.inst.query("SOURce1:PULSe:TRANsition:TRAiling?").strip()
            state = self.inst.query("OUTPut1:STATe?").strip()
        except pyvisa.VisaIOError as exc:
            self._log(f"Query failed: {exc}")
            return
        self._log(f"Shape: {shape}")
        self._log(f"Period: {period} s")
        try:
            per_val = float(period)
            if per_val > 0:
                self._log(f"Freq : {1.0 / per_val} Hz")
        except ValueError:
            pass
        self._log(f"Width: {width} s")
        self._log(f"Duty : {duty} %")
        self._log(f"High : {high} V")
        self._log(f"Low  : {low} V")
        self._log(f"Rise : {lead} s")
        self._log(f"Fall : {trail} s")
        self._log(f"Out  : {state}")

    def drain_errors(self) -> None:
        if not self._check_connection():
            return
        try:
            for _ in range(8):
                err = self.inst.query("SYSTem:ERRor?").strip()
                self._log(f"ERR: {err}")
                if err.startswith("0,"):
                    break
        except pyvisa.VisaIOError as exc:
            self._log(f"Error query failed: {exc}")

    # ----------------------------- Helpers ---------------------------------
    def _update_period_hint(self) -> None:
        try:
            freq = float(self.freq_var.get())
            if freq > 0:
                self.period_hint_var.set(f"Period ≈ {self._format_seconds(freq)}")
                return
        except ValueError:
            pass
        self.period_hint_var.set("Period: —")

    @staticmethod
    def _format_seconds(freq_hz: float) -> str:
        period = 1.0 / freq_hz
        if period >= 1:
            return f"{period:g} s"
        if period >= 1e-3:
            return f"{period*1e3:g} ms"
        if period >= 1e-6:
            return f"{period*1e6:g} us"
        if period >= 1e-9:
            return f"{period*1e9:g} ns"
        return f"{period*1e12:g} ps"

    def on_close(self) -> None:
        self.disconnect()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    VisaConsoleApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
