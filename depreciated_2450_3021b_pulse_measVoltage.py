from __future__ import annotations

import pathlib
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import pyvisa
from pyvisa import constants as visa_constants

ROOT = pathlib.Path(__file__).resolve().parent
KEITHLEY_TSP_PATH = ROOT / "2450" / "2450_async_trigger_measure_voltage.tsp"
DEFAULT_2450_ADDRESS = "TCPIP0::169.254.188.69::5025::SOCKET"
DEFAULT_3021B_ADDRESS = "TCPIP0::169.254.6.24::inst0::INSTR"
RECEIVE_TRIGGER_SCRIPT_NAME = "ReceiveTrigger"
DEFAULT_MEASURE_RANGE = "2"
DEFAULT_MEASURE_NPLC = "0.01"
TRIGGER_MODE_OPTIONS = ("SYNC", "*TRG")
FIXED_CAPTURE_INTERVAL_S = 0.0002  # 200 microseconds

RECEIVE_TRIGGER_SCRIPT = """
loadscript ReceiveTrigger
local receive_trigger_cancel_flag = false
local DEFAULT_EDGE = "falling"
local EDGE_MAP = { rising = trigger.EDGE_RISING, falling = trigger.EDGE_FALLING, either = trigger.EDGE_EITHER }
local DEFAULT_LINE = 1
local DEFAULT_MODE = "trigger_in"
local MODE_MAP = {
    digital_in = digio.MODE_DIGITAL_IN,
    digital_out = digio.MODE_DIGITAL_OUT,
    digital_open_drain = digio.MODE_DIGITAL_OPEN_DRAIN,
    trigger_in = digio.MODE_TRIGGER_IN,
    trigger_out = digio.MODE_TRIGGER_OUT,
    trigger_open_drain = digio.MODE_TRIGGER_OPEN_DRAIN,
    synchronous_master = digio.MODE_SYNCHRONOUS_MASTER,
    synchronous_acceptor = digio.MODE_SYNCHRONOUS_ACCEPTOR
}

local function resolve_edge(edge_name)
    if edge_name == nil then
        return EDGE_MAP[DEFAULT_EDGE]
    end
    local edge = EDGE_MAP[string.lower(tostring(edge_name))]
    if edge == nil then
        return EDGE_MAP[DEFAULT_EDGE]
    end
    return edge
end

local function normalize_mode_key(mode_name)
    if mode_name == nil then return DEFAULT_MODE end
    local key = string.lower(tostring(mode_name))
    key = string.gsub(key, "%s+", "_")
    return key
end

local function resolve_mode(mode_name)
    local key = normalize_mode_key(mode_name)
    local mode = MODE_MAP[key]
    if mode == nil then
        return MODE_MAP[DEFAULT_MODE], DEFAULT_MODE
    end
    return mode, key
end

local function resolve_line(line_number)
    local idx = tonumber(line_number) or DEFAULT_LINE
    if idx < 1 then idx = 1 elseif idx > 6 then idx = 6 end
    return math.floor(idx + 0.0001)
end

local function is_trigger_input_mode(mode_value)
    return mode_value == digio.MODE_TRIGGER_IN or mode_value == digio.MODE_TRIGGER_OPEN_DRAIN
end

local function ensure_line(line_number, edge, mode_value)
    digio.line[line_number].mode = mode_value
    if is_trigger_input_mode(mode_value) then
        trigger.digin[line_number].edge = edge
        trigger.digin[line_number].clear()
    end
end

function receive_trigger_setup(edge_name, line_number, mode_name)
    local edge = resolve_edge(edge_name)
    local mode_value, mode_label = resolve_mode(mode_name)
    local line = resolve_line(line_number)
    ensure_line(line, edge, mode_value)
    receive_trigger_cancel_flag = false
    display.changescreen(display.SCREEN_USER_SWIPE)
    local info = string.format("DIGIO%d (%s)", line, mode_label)
    display.settext(display.TEXT1, "Waiting for trigger")
    display.settext(display.TEXT2, info)
end

function receive_trigger_wait(timeout, edge_name, line_number, mode_name)
    local edge = resolve_edge(edge_name)
    local mode_value, mode_label = resolve_mode(mode_name)
    local line = resolve_line(line_number)
    ensure_line(line, edge, mode_value)
    if not is_trigger_input_mode(mode_value) then
        return "INVALID_MODE"
    end
    receive_trigger_cancel_flag = false
    local chunk = 0.25
    local elapsed = 0
    while not receive_trigger_cancel_flag do
        local wait_time = chunk
        if timeout ~= nil then
            if timeout <= elapsed then break end
            if elapsed + wait_time > timeout then
                wait_time = timeout - elapsed
            end
        end
        if wait_time <= 0 then break end
        if trigger.digin[line].wait(wait_time) then
            display.settext(display.TEXT1, "Trigger received")
            display.settext(display.TEXT2, "")
            return "TRIGGER"
        end
        if timeout ~= nil then
            elapsed = elapsed + wait_time
        end
    end
    if receive_trigger_cancel_flag then
        display.settext(display.TEXT1, "Cancelled")
        display.settext(display.TEXT2, "")
        return "CANCEL"
    end
    display.settext(display.TEXT1, "Timeout")
    display.settext(display.TEXT2, "")
    return "TIMEOUT"
end

function receive_trigger_cancel()
    receive_trigger_cancel_flag = true
end

function receive_trigger_clear_display()
    display.changescreen(display.SCREEN_USER_SWIPE)
    display.settext(display.TEXT1, "")
    display.settext(display.TEXT2, "")
end
endscript
"""


class Tek3021BPulsePanel:
    def __init__(self, parent: tk.Misc) -> None:
        self.parent = parent
        self.rm: pyvisa.ResourceManager | None = None
        self.inst: pyvisa.resources.MessageBasedResource | None = None
        self.address_var = tk.StringVar(value=DEFAULT_3021B_ADDRESS)
        self.cmd_var = tk.StringVar(value="*IDN?")
        self.timeout_var = tk.StringVar(value="5000")
        self.freq_var = tk.StringVar(value="1000")
        self.width_var = tk.StringVar(value="50e-6")
        self.duty_var = tk.StringVar(value="5.0")
        self.high_var = tk.StringVar(value="1.0")
        self.low_var = tk.StringVar(value="0.0")
        self.lead_var = tk.StringVar(value="20e-9")
        self.trail_var = tk.StringVar(value="20e-9")
        self.load_var = tk.StringVar(value="INF")
        self.phase_var = tk.StringVar(value="0")
        self.hold_var = tk.StringVar(value="WIDTh")
        self.period_hint_var = tk.StringVar(value="Period: —")
        self.trigger_mode_var = tk.StringVar(value=TRIGGER_MODE_OPTIONS[0])

        self._build_ui(parent)
        try:
            self.freq_var.trace_add("write", lambda *_: self._update_period_hint())
        except AttributeError:
            self.freq_var.trace("w", lambda *_: self._update_period_hint())
        self._update_period_hint()

    def _build_ui(self, parent: tk.Misc) -> None:
        container = ttk.Frame(parent, padding=10)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(1, weight=1)
        container.rowconfigure(3, weight=1)

        ttk.Label(container, text="VISA address:").grid(row=0, column=0, sticky="w")
        ttk.Entry(container, textvariable=self.address_var, width=32).grid(row=0, column=1, columnspan=3, sticky="we", padx=(4, 8))
        ttk.Label(container, text="Timeout (ms):").grid(row=0, column=4, sticky="e")
        ttk.Entry(container, textvariable=self.timeout_var, width=8).grid(row=0, column=5, sticky="w")
        self.btn_connect = ttk.Button(container, text="Connect", command=self.connect)
        self.btn_connect.grid(row=0, column=6, padx=(8, 0))
        self.btn_disconnect = ttk.Button(container, text="Disconnect", state="disabled", command=self.disconnect)
        self.btn_disconnect.grid(row=0, column=7, padx=(4, 0))

        pulse = ttk.LabelFrame(container, text="Pulse Setup")
        pulse.grid(row=1, column=0, columnspan=8, sticky="ew", pady=(10, 6))
        for idx in range(8):
            if idx % 2 == 1:
                pulse.columnconfigure(idx, weight=1)

        ttk.Label(pulse, text="Frequency (Hz)").grid(row=0, column=0, sticky="w", padx=(4, 0))
        freq_wrap = ttk.Frame(pulse)
        freq_wrap.grid(row=0, column=1, sticky="we", padx=(4, 10))
        ttk.Entry(freq_wrap, textvariable=self.freq_var, width=12).pack(side=tk.LEFT)
        ttk.Label(freq_wrap, textvariable=self.period_hint_var).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(pulse, text="Pulse width (s)").grid(row=0, column=2, sticky="w")
        ttk.Entry(pulse, textvariable=self.width_var, width=12).grid(row=0, column=3, sticky="w", padx=(4, 10))

        ttk.Label(pulse, text="Duty (%)").grid(row=0, column=4, sticky="w")
        ttk.Entry(pulse, textvariable=self.duty_var, width=10).grid(row=0, column=5, sticky="w", padx=(4, 10))

        ttk.Label(pulse, text="Hold").grid(row=0, column=6, sticky="e")
        ttk.Combobox(pulse, textvariable=self.hold_var, values=("WIDTh", "DUTY"), state="readonly", width=8).grid(row=0, column=7, sticky="w")

        ttk.Label(pulse, text="High level (V)").grid(row=1, column=0, sticky="w", padx=(4, 0), pady=(6, 0))
        ttk.Entry(pulse, textvariable=self.high_var, width=12).grid(row=1, column=1, sticky="w", padx=(4, 10), pady=(6, 0))
        ttk.Label(pulse, text="Low level (V)").grid(row=1, column=2, sticky="w", pady=(6, 0))
        ttk.Entry(pulse, textvariable=self.low_var, width=12).grid(row=1, column=3, sticky="w", padx=(4, 10), pady=(6, 0))
        ttk.Label(pulse, text="Rise (s)").grid(row=1, column=4, sticky="w", pady=(6, 0))
        ttk.Entry(pulse, textvariable=self.lead_var, width=10).grid(row=1, column=5, sticky="w", padx=(4, 10), pady=(6, 0))
        ttk.Label(pulse, text="Fall (s)").grid(row=1, column=6, sticky="w", pady=(6, 0))
        ttk.Entry(pulse, textvariable=self.trail_var, width=10).grid(row=1, column=7, sticky="w", pady=(6, 0))

        ttk.Label(pulse, text="Load (Ω or INF)").grid(row=2, column=0, sticky="w", padx=(4, 0), pady=(6, 0))
        ttk.Entry(pulse, textvariable=self.load_var, width=12).grid(row=2, column=1, sticky="w", padx=(4, 10), pady=(6, 0))
        ttk.Label(pulse, text="Phase (deg)").grid(row=2, column=2, sticky="w", pady=(6, 0))
        ttk.Entry(pulse, textvariable=self.phase_var, width=12).grid(row=2, column=3, sticky="w", padx=(4, 10), pady=(6, 0))
        ttk.Label(pulse, text="Trigger mode").grid(row=2, column=4, sticky="e", pady=(6, 0))
        ttk.Combobox(
            pulse,
            textvariable=self.trigger_mode_var,
            values=TRIGGER_MODE_OPTIONS,
            state="readonly",
            width=8,
        ).grid(row=2, column=5, sticky="w", pady=(6, 0))

        pulse_btns = ttk.Frame(pulse)
        pulse_btns.grid(row=3, column=0, columnspan=8, sticky="ew", pady=(8, 0))
        pulse_btns.columnconfigure((0, 1, 2, 3), weight=1)
        ttk.Button(pulse_btns, text="Apply Pulse Setup", command=self.apply_pulse).grid(row=0, column=0, padx=4)
        ttk.Button(pulse_btns, text="Output ON", command=self.output_on).grid(row=0, column=1, padx=4)
        ttk.Button(pulse_btns, text="Output OFF", command=self.output_off).grid(row=0, column=2, padx=4)
        ttk.Button(pulse_btns, text="Query", command=self.query_pulse).grid(row=0, column=3, padx=4)
        ttk.Button(pulse_btns, text="Errors", command=self.drain_errors).grid(row=0, column=4, padx=4)

        console_frame = ttk.LabelFrame(container, text="Console")
        console_frame.grid(row=2, column=0, columnspan=8, sticky="nsew", pady=(10, 0))
        self.console = scrolledtext.ScrolledText(console_frame, height=12, state=tk.DISABLED)
        self.console.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        cmd_bar = ttk.Frame(container)
        cmd_bar.grid(row=3, column=0, columnspan=8, sticky="ew", pady=(8, 0))
        ttk.Label(cmd_bar, text="SCPI Command:").pack(side=tk.LEFT)
        entry = ttk.Entry(cmd_bar, textvariable=self.cmd_var)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))
        entry.bind("<Return>", lambda _event: self.write_command())
        ttk.Button(cmd_bar, text="Write", command=self.write_command).pack(side=tk.LEFT, padx=2)
        ttk.Button(cmd_bar, text="Query", command=self.query_command).pack(side=tk.LEFT, padx=2)
        ttk.Button(cmd_bar, text="Read", command=self.read_only).pack(side=tk.LEFT, padx=2)
        ttk.Button(cmd_bar, text="Clear", command=self.clear_console).pack(side=tk.LEFT, padx=2)

    def connect(self) -> None:
        address = self.address_var.get().strip()
        if not address:
            messagebox.showerror("3021B", "Enter a VISA address.")
            return
        timeout = self._parse_timeout()
        try:
            if self.rm is None:
                self.rm = pyvisa.ResourceManager()
            self.inst = self.rm.open_resource(address)
            self.inst.timeout = timeout
            self.inst.read_termination = "\n"
            self.inst.write_termination = "\n"
            idn = self.inst.query("*IDN?").strip()
            self._log(f"Connected to {idn}")
            self.btn_connect.configure(state="disabled")
            self.btn_disconnect.configure(state="normal")
        except pyvisa.VisaIOError as exc:
            messagebox.showerror("3021B", str(exc))
            self._log(f"Connect failed: {exc}")
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
        self.btn_connect.configure(state="normal")
        self.btn_disconnect.configure(state="disabled")
        self._log("Disconnected.")

    def shutdown_outputs(self) -> None:
        try:
            self.output_off()
        except Exception:
            pass
        self.disconnect()

    def write_command(self) -> None:
        cmd = self.cmd_var.get().strip()
        if not cmd or not self._check_inst():
            return
        try:
            self.inst.write(cmd)
            self._log(f"> {cmd}")
        except pyvisa.VisaIOError as exc:
            self._log(f"Write error: {exc}")

    def query_command(self) -> None:
        cmd = self.cmd_var.get().strip()
        if not cmd or not self._check_inst():
            return
        try:
            resp = self.inst.query(cmd).strip()
            self._log(f"> {cmd}")
            self._log(f"< {resp}")
        except pyvisa.VisaIOError as exc:
            self._log(f"Query error: {exc}")

    def read_only(self) -> None:
        if not self._check_inst():
            return
        try:
            resp = self.inst.read().strip()
            self._log(f"< {resp}")
        except pyvisa.VisaIOError as exc:
            self._log(f"Read error: {exc}")

    def apply_pulse(self) -> None:
        try:
            inst = self._program_pulse_from_gui(interactive=True)
            self._configure_trigger_mode(inst)
        except Exception:
            return

    def apply_gui_setup_for_trigger(self) -> None:
        inst = self._program_pulse_from_gui(interactive=False)
        mode = self._configure_trigger_mode(inst)
        try:
            inst.write("OUTPut1:STATe ON")
        except pyvisa.VisaIOError as exc:
            self._log(f"Output ON failed: {exc}")
            raise
        if mode == "*TRG":
            inst.write("*TRG")
            self._log("Issued *TRG to launch burst with current GUI setup.")
        else:
            self._log("SYNC mode armed; waiting for external sync trigger pulse.")

    def output_on(self) -> None:
        if self._check_inst():
            try:
                self.inst.write("OUTPut1:STATe ON")
                self._log("Output ON")
            except pyvisa.VisaIOError as exc:
                self._log(f"Output ON failed: {exc}")

    def output_off(self) -> None:
        if self._check_inst():
            try:
                self.inst.write("OUTPut1:STATe OFF")
                self._log("Output OFF")
            except pyvisa.VisaIOError as exc:
                self._log(f"Output OFF failed: {exc}")

    def query_pulse(self) -> None:
        if not self._check_inst():
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
        if not self._check_inst():
            return
        try:
            for _ in range(8):
                err = self.inst.query("SYSTem:ERRor?").strip()
                self._log(f"ERR: {err}")
                if err.startswith("0,"):
                    break
        except pyvisa.VisaIOError as exc:
            self._log(f"Error read failed: {exc}")

    def clear_console(self) -> None:
        self.console.configure(state=tk.NORMAL)
        self.console.delete("1.0", tk.END)
        self.console.configure(state=tk.DISABLED)

    def _check_inst(self) -> bool:
        if self.inst is None:
            messagebox.showwarning("3021B", "Connect to the instrument first.")
            return False
        return True

    def _parse_timeout(self) -> int:
        value = self.timeout_var.get().strip()
        try:
            timeout = int(float(value))
        except ValueError:
            timeout = 5000
            self.timeout_var.set(str(timeout))
        return max(timeout, 100)

    def _log(self, message: str) -> None:
        self.console.configure(state=tk.NORMAL)
        self.console.insert(tk.END, message + "\n")
        self.console.see(tk.END)
        self.console.configure(state=tk.DISABLED)

    def _require_instrument(
        self, *, interactive: bool
    ) -> pyvisa.resources.MessageBasedResource:
        if self.inst is not None:
            return self.inst
        if interactive:
            messagebox.showwarning("3021B", "Connect to the instrument first.")
        raise RuntimeError("Tektronix 3021B is not connected.")

    def _program_pulse_from_gui(
        self, *, interactive: bool
    ) -> pyvisa.resources.MessageBasedResource:
        inst = self._require_instrument(interactive=interactive)
        try:
            freq = float(self.freq_var.get())
            width_entry = float(self.width_var.get())
            duty_entry = float(self.duty_var.get())
            high = float(self.high_var.get())
            low = float(self.low_var.get())
        except ValueError as exc:
            if interactive:
                messagebox.showerror("3021B", f"Invalid numeric entry: {exc}")
            raise
        if freq <= 0:
            if interactive:
                messagebox.showerror("3021B", "Frequency must be > 0.")
            raise ValueError("Frequency must be positive.")
        period = 1.0 / freq
        hold = self.hold_var.get().strip().upper() or "WIDTH"
        if hold not in {"WIDTH", "DUTY"}:
            hold = "WIDTH"
            self.hold_var.set("WIDTh")
        if hold == "WIDTH":
            width = width_entry
            if width <= 0 or width >= period:
                if interactive:
                    messagebox.showerror("3021B", "Width must be inside (0, period).")
                raise ValueError("Width must be inside (0, period).")
            duty = 100.0 * width / period
            self.duty_var.set(f"{duty:.6g}")
        else:
            duty = duty_entry
            if not 0 < duty < 100:
                if interactive:
                    messagebox.showerror("3021B", "Duty cycle must be 0-100%.")
                raise ValueError("Duty cycle must be between 0 and 100%.")
            width = period * duty / 100.0
            if width <= 0 or width >= period:
                if interactive:
                    messagebox.showerror("3021B", "Duty/period combination invalid.")
                raise ValueError("Duty/period combination invalid.")
            self.width_var.set(f"{width:.6g}")
        load_txt = self.load_var.get().strip().upper()
        lead = self.lead_var.get().strip()
        trail = self.trail_var.get().strip()
        phase_txt = self.phase_var.get().strip()
        try:
            inst.write("OUTPut1:STATe OFF")
            if load_txt:
                if load_txt in {"INF", "INFINITE", "HIGHZ"}:
                    inst.write("OUTPut1:IMPedance INF")
                else:
                    load_val = float(load_txt)
                    if load_val <= 0:
                        raise ValueError("Load must be > 0.")
                    inst.write(f"OUTPut1:IMPedance {load_val}")
            inst.write("*CLS")
            inst.write("SOURce1:FUNCtion:SHAPe PULSe")
            inst.write(f"SOURce1:PULSe:PERiod {period}")
            hold_cmd = "WIDTh" if hold == "WIDTH" else "DUTY"
            inst.write(f"SOURce1:PULSe:HOLD {hold_cmd}")
            if hold == "WIDTH":
                inst.write(f"SOURce1:PULSe:WIDTh {width}")
            else:
                inst.write(f"SOURce1:PULSe:DCYCle {duty}")
            inst.write(f"SOURce1:VOLTage:LEVel:IMMediate:HIGH {high}")
            inst.write(f"SOURce1:VOLTage:LEVel:IMMediate:LOW {low}")
            if lead:
                inst.write(f"SOURce1:PULSe:TRANsition:LEADing {lead}")
            if trail:
                inst.write(f"SOURce1:PULSe:TRANsition:TRAiling {trail}")
            if phase_txt:
                phase = float(phase_txt)
                inst.write(f"SOURce1:PHASe {phase}")
        except (ValueError, pyvisa.VisaIOError) as exc:
            if interactive:
                messagebox.showerror("3021B", str(exc))
            self._log(f"Pulse apply failed: {exc}")
            raise
        self._log(
            f"Pulse applied: freq={freq} Hz, width={width} s, duty={duty}%, high={high} V, low={low} V"
        )
        self._update_period_hint()
        return inst

    def _configure_trigger_mode(
        self, inst: pyvisa.resources.MessageBasedResource
    ) -> str:
        selection = self.trigger_mode_var.get().strip().upper()
        if selection == "*TRG":
            inst.write("OUTP:TRIG:MODE TRIG")
            inst.write("TRIG:SEQ:SOUR BUS")
            self._log("Trigger mode set to *TRG (software bus).")
            return "*TRG"
        inst.write("OUTP:TRIG:MODE SYNC")
        inst.write("TRIG:SEQ:SOUR EXT")
        self._log("Trigger mode set to SYNC (external input).")
        return "SYNC"

    def _update_period_hint(self) -> None:
        try:
            freq = float(self.freq_var.get())
            if freq > 0:
                period = 1.0 / freq
                self.period_hint_var.set(f"Period ≈ {self._format_seconds(period)}")
                return
        except ValueError:
            pass
        self.period_hint_var.set("Period: —")

    @staticmethod
    def _format_seconds(value: float) -> str:
        v = float(value)
        if v >= 1:
            return f"{v:g} s"
        if v >= 1e-3:
            return f"{v*1e3:g} ms"
        if v >= 1e-6:
            return f"{v*1e6:g} us"
        if v >= 1e-9:
            return f"{v*1e9:g} ns"
        return f"{v*1e12:g} ps"


class Keithley2450Session:
    def __init__(self) -> None:
        self.rm: pyvisa.ResourceManager | None = None
        self.inst: pyvisa.resources.MessageBasedResource | None = None
        self.address = DEFAULT_2450_ADDRESS
        self._callbacks: list[callable] = []
        self._loaded_scripts: set[str] = set()

    def register_callback(self, callback: callable) -> None:
        self._callbacks.append(callback)

    def _notify(self) -> None:
        for cb in self._callbacks:
            try:
                cb(self)
            except Exception:
                pass

    def connect(self, address: str) -> str:
        addr = address.strip()
        if not addr:
            raise ValueError("Provide a VISA address for the 2450.")
        self.address = addr
        if self.rm is None:
            self.rm = pyvisa.ResourceManager()
        self.inst = self.rm.open_resource(addr)
        self.inst.read_termination = "\n"
        self.inst.write_termination = "\n"
        self.inst.timeout = 20000
        idn = self.inst.query("*IDN?").strip()
        self._loaded_scripts.clear()
        self._notify()
        return idn

    def disconnect(self) -> None:
        if self.inst:
            try:
                self.inst.close()
            except pyvisa.VisaIOError:
                pass
        if self.rm:
            try:
                self.rm.close()
            except pyvisa.VisaIOError:
                pass
        self.inst = None
        self.rm = None
        self._loaded_scripts.clear()
        self._notify()

    def ensure_script(self, name: str, script_text: str) -> None:
        if self.inst is None:
            raise RuntimeError("Connect to the 2450 first.")
        if name in self._loaded_scripts:
            return
        try:
            self.inst.write(f"pcall(script.delete, '{name}')")
        except pyvisa.VisaIOError:
            pass
        for line in script_text.strip().splitlines():
            self.inst.write(line)
        self.inst.write(f"{name}.save()")
        self.inst.write(f"{name}()")
        self._loaded_scripts.add(name)

    def ensure_script_from_path(self, name: str, path: pathlib.Path) -> None:
        if not path.exists():
            raise FileNotFoundError(f"Missing TSP file: {path}")
        raw = path.read_text(encoding="utf-8")
        stripped = raw.lstrip()
        if stripped.lower().startswith("loadscript"):
            script_text = raw
        else:
            body = raw.strip()
            script_text = f"loadscript {name}\n{body}\n\nendscript"
        self.ensure_script(name, script_text)

    def write(self, command: str) -> None:
        if self.inst is None:
            raise RuntimeError("Connect to the 2450 first.")
        self.inst.write(command)

    def query(self, command: str) -> str:
        if self.inst is None:
            raise RuntimeError("Connect to the 2450 first.")
        return self.inst.query(command)


class TriggerOptionsPanel:
    EDGE_OPTIONS = ("falling", "rising", "either")
    LINE_OPTIONS = ("1", "2", "3", "4", "5", "6")
    MODE_CHOICES = (
        ("Trigger control, input", "trigger_in"),
        ("Trigger control, open-drain", "trigger_open_drain"),
        ("Trigger control, output", "trigger_out"),
        ("Digital control, input", "digital_in"),
        ("Digital control, output", "digital_out"),
        ("Digital control, open-drain", "digital_open_drain"),
        ("Synchronous master", "synchronous_master"),
        ("Synchronous acceptor", "synchronous_acceptor"),
    )

    def __init__(
        self,
        parent: tk.Misc,
        session: Keithley2450Session,
        address_var: tk.StringVar,
        trigger_callback: callable | None = None,
        before_wait_callback: callable | None = None,
    ) -> None:
        self.parent = parent
        self.session = session
        self.address_var = address_var
        self.trigger_callback = trigger_callback
        self.before_wait_callback = before_wait_callback
        self.edge_var = tk.StringVar(value=self.EDGE_OPTIONS[0])
        self.line_var = tk.StringVar(value=self.LINE_OPTIONS[0])
        self.mode_var = tk.StringVar(value=self.MODE_CHOICES[0][0])
        self.timeout_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Disconnected")
        self.wait_thread: threading.Thread | None = None
        self.waiting = False

        self._build_ui(parent)
        self.session.register_callback(self._on_session_change)

    def _build_ui(self, frame: tk.Misc) -> None:
        container = ttk.Frame(frame, padding=8)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(1, weight=1)
        container.rowconfigure(7, weight=1)

        ttk.Label(container, text="2450 VISA:").grid(column=0, row=0, sticky="w")
        ttk.Entry(container, textvariable=self.address_var, width=34).grid(column=1, row=0, sticky="we", padx=(4, 8))
        btns = ttk.Frame(container)
        btns.grid(column=0, row=1, columnspan=2, sticky="w", pady=(6, 0))
        self.btn_connect = ttk.Button(btns, text="Connect", command=self.connect)
        self.btn_connect.pack(side=tk.LEFT)
        self.btn_disconnect = ttk.Button(btns, text="Disconnect", command=self.disconnect, state="disabled")
        self.btn_disconnect.pack(side=tk.LEFT, padx=6)

        ttk.Label(container, text="Edge").grid(column=0, row=2, sticky="w", pady=(8, 0))
        ttk.Combobox(container, textvariable=self.edge_var, values=self.EDGE_OPTIONS, state="readonly", width=12).grid(column=1, row=2, sticky="w", pady=(8, 0))

        ttk.Label(container, text="DIGIO line").grid(column=0, row=3, sticky="w")
        ttk.Combobox(container, textvariable=self.line_var, values=self.LINE_OPTIONS, state="readonly", width=8).grid(column=1, row=3, sticky="w")

        ttk.Label(container, text="Line mode").grid(column=0, row=4, sticky="w")
        ttk.Combobox(
            container,
            textvariable=self.mode_var,
            values=[label for label, _ in self.MODE_CHOICES],
            state="readonly",
            width=28,
        ).grid(column=1, row=4, sticky="w")

        ttk.Label(container, text="Timeout (s, blank = ∞)").grid(column=0, row=5, sticky="w")
        ttk.Entry(container, textvariable=self.timeout_var, width=12).grid(column=1, row=5, sticky="w")

        action_row = ttk.Frame(container)
        action_row.grid(column=0, row=6, columnspan=2, pady=(10, 0), sticky="we")
        for i in range(4):
            action_row.columnconfigure(i, weight=1)
        self.btn_setup = ttk.Button(action_row, text="Setup", command=self.setup_trigger, state="disabled")
        self.btn_setup.grid(column=0, row=0, padx=4)
        self.btn_wait = ttk.Button(action_row, text="Wait", command=self.start_wait, state="disabled")
        self.btn_wait.grid(column=1, row=0, padx=4)
        self.btn_cancel = ttk.Button(action_row, text="Cancel", command=self.cancel_wait, state="disabled")
        self.btn_cancel.grid(column=2, row=0, padx=4)
        self.btn_clear = ttk.Button(action_row, text="Clear", command=self.clear_display, state="disabled")
        self.btn_clear.grid(column=3, row=0, padx=4)

        self.log = scrolledtext.ScrolledText(container, height=12, state=tk.DISABLED)
        self.log.grid(column=0, row=7, columnspan=2, sticky="nsew", pady=(10, 0))

        ttk.Label(container, textvariable=self.status_var, anchor="w").grid(column=0, row=8, columnspan=2, sticky="we", pady=(6, 0))

    def _log(self, message: str) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, message + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _on_session_change(self, session: Keithley2450Session) -> None:
        connected = session.inst is not None
        state = "normal" if connected else "disabled"
        self.btn_disconnect.configure(state="normal" if connected else "disabled")
        self.btn_connect.configure(state="disabled" if connected else "normal")
        self.btn_setup.configure(state=state)
        self.btn_wait.configure(state=state if not self.waiting else "disabled")
        self.btn_cancel.configure(state="normal" if self.waiting else "disabled")
        self.btn_clear.configure(state=state)
        self.status_var.set("Connected" if connected else "Disconnected")

    def connect(self) -> None:
        try:
            idn = self.session.connect(self.address_var.get())
            self.session.ensure_script(RECEIVE_TRIGGER_SCRIPT_NAME, RECEIVE_TRIGGER_SCRIPT)
            self.status_var.set(f"Connected to {idn}")
            self._log(f"Connected: {idn}")
        except Exception as exc:
            messagebox.showerror("2450", str(exc))
            self._log(f"Connect failed: {exc}")

    def disconnect(self) -> None:
        if self.waiting:
            messagebox.showinfo("2450", "Stop waiting before disconnecting.")
            return
        self.session.disconnect()
        self._log("Disconnected.")

    def _resolve_line(self) -> int:
        try:
            number = int(self.line_var.get())
        except ValueError as exc:
            raise ValueError("Select a DIGIO line 1-6.") from exc
        if not 1 <= number <= 6:
            raise ValueError("DIGIO line must be 1-6.")
        return number

    def _resolve_mode(self) -> str:
        label = self.mode_var.get()
        for nice, key in self.MODE_CHOICES:
            if label == nice:
                return key
        raise ValueError("Select a valid line mode.")

    def setup_trigger(self) -> None:
        if self.session.inst is None:
            messagebox.showwarning("2450", "Connect first.")
            return
        try:
            line = self._resolve_line()
            mode_key = self._resolve_mode()
            edge = self.edge_var.get().strip().lower()
            cmd = f"receive_trigger_setup('{edge}', {line}, '{mode_key}')"
            self.session.write(cmd)
            self._log(f"Setup DIGIO{line} ({mode_key}) edge={edge}.")
        except Exception as exc:
            messagebox.showerror("2450", str(exc))
            self._log(f"Setup failed: {exc}")

    def start_wait(self) -> None:
        if self.session.inst is None:
            messagebox.showwarning("2450", "Connect first.")
            return
        if self.waiting:
            messagebox.showinfo("2450", "Already waiting for a trigger.")
            return
        try:
            timeout = self.timeout_var.get().strip()
            timeout_expr = "nil" if not timeout else str(float(timeout))
            line = self._resolve_line()
            mode_key = self._resolve_mode()
            edge = self.edge_var.get().strip().lower()
        except ValueError as exc:
            messagebox.showerror("2450", str(exc))
            return
        if self.before_wait_callback:
            ready = self.before_wait_callback()
            if ready is False:
                self._log("Wait cancelled: meter prep failed.")
                return
        self.waiting = True
        self.btn_wait.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self._log(
            f"Waiting on DIGIO{line} ({mode_key}) edge={edge or 'default'} timeout={timeout or '∞'}"
        )
        self.wait_thread = threading.Thread(
            target=self._wait_worker,
            args=(timeout_expr, edge, line, mode_key),
            daemon=True,
        )
        self.wait_thread.start()

    def _wait_worker(self, timeout_expr: str, edge: str, line: int, mode_key: str) -> None:
        edge_arg = f"'{edge}'" if edge else "nil"
        cmd = f"print(receive_trigger_wait({timeout_expr}, {edge_arg}, {line}, '{mode_key}'))"
        try:
            result = self.session.query(cmd).strip().upper()
        except Exception as exc:
            self.parent.after(0, lambda: self._handle_wait_result(error=str(exc)))
            return
        self.parent.after(0, lambda: self._handle_wait_result(result=result))

    def _handle_wait_result(self, result: str | None = None, error: str | None = None) -> None:
        self.waiting = False
        self.btn_wait.configure(state="normal" if self.session.inst else "disabled")
        self.btn_cancel.configure(state="disabled")
        if error:
            self._log(f"Wait failed: {error}")
            messagebox.showerror("2450", f"Wait failed: {error}")
            return
        if result == "TRIGGER":
            self._log("Trigger received.")
            if self.trigger_callback:
                try:
                    self.trigger_callback()
                except Exception as exc:
                    self._log(f"Trigger callback failed: {exc}")
        elif result == "TIMEOUT":
            self._log("Timeout waiting for trigger.")
        elif result == "CANCEL":
            self._log("Wait cancelled.")
        elif result == "INVALID_MODE":
            self._log("DIGIO mode is not a trigger input.")
        else:
            self._log(f"Wait result: {result}")

    def cancel_wait(self) -> None:
        if not self.waiting or self.session.inst is None:
            return
        try:
            self.session.write("receive_trigger_cancel()")
            self._log("Cancel requested.")
        except Exception as exc:
            self._log(f"Cancel failed: {exc}")

    def clear_display(self) -> None:
        if self.session.inst is None:
            return
        try:
            self.session.write("receive_trigger_clear_display()")
            self._log("Display cleared.")
        except Exception as exc:
            self._log(f"Clear failed: {exc}")


class AsyncMeasurePanel:
    SCRIPT_NAME = "TriggerVoltmeter"
    DRAIN_TIMEOUT_MS = 250

    def __init__(
        self,
        parent: tk.Misc,
        session: Keithley2450Session,
        *,
        trigger_sync_callback: callable | None = None,
        shutdown_callback: callable | None = None,
    ) -> None:
        self.parent = parent
        self.session = session
        self.range_var = tk.StringVar(value=DEFAULT_MEASURE_RANGE)
        self.auto_count_var = tk.StringVar(value="25")
        self.trigger_sync_callback = trigger_sync_callback
        self.shutdown_callback = shutdown_callback
        self.log_box: tk.Text | None = None
        self.ax = None
        self.canvas: FigureCanvasTkAgg | None = None
        self.figure = None
        self._armed_for_trigger = False
        self._armed_range: str | None = None
        self._armed_nplc: str | None = None

        self._build_ui(parent)
        self.session.register_callback(self._on_session_change)

    def _build_ui(self, frame: tk.Misc) -> None:
        container = ttk.Frame(frame, padding=8)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(2, weight=1)
        container.rowconfigure(3, weight=2)

        config_box = ttk.LabelFrame(container, text="Meter Configuration")
        config_box.grid(column=0, row=0, sticky="ew")
        config_box.columnconfigure(3, weight=1)
        ttk.Label(config_box, text="Range (V)").grid(column=0, row=0, sticky="e")
        ttk.Entry(config_box, textvariable=self.range_var, width=10).grid(column=1, row=0, sticky="w", padx=(4, 12))
        ttk.Label(config_box, text="Integration").grid(column=2, row=0, sticky="e")
        ttk.Label(
            config_box,
            text="0.01 NPLC (~200 us)",
        ).grid(column=3, row=0, sticky="w")
        self.btn_configure = ttk.Button(config_box, text="Configure", command=self.configure_meter, state="disabled")
        self.btn_configure.grid(column=4, row=0, padx=(8, 0))
        self.btn_output_off = ttk.Button(config_box, text="Output Off", command=self.output_off, state="disabled")
        self.btn_output_off.grid(column=5, row=0, padx=(8, 0))

        auto_box = ttk.LabelFrame(container, text="Automatic Capture")
        auto_box.grid(column=0, row=1, sticky="ew", pady=(10, 0))
        ttk.Label(auto_box, text="Samples").grid(column=0, row=0, sticky="e")
        ttk.Entry(auto_box, textvariable=self.auto_count_var, width=8).grid(column=1, row=0, sticky="w", padx=(4, 16))
        ttk.Label(auto_box, text="Interval").grid(column=2, row=0, sticky="e")
        ttk.Label(auto_box, text="Fixed 0.0002 s (0.01 NPLC)").grid(column=3, row=0, sticky="w", padx=(4, 16))
        self.btn_auto = ttk.Button(auto_box, text="Run Sequence", command=self.run_auto_trigger, state="disabled")
        self.btn_auto.grid(column=4, row=0, padx=6)

        self.log_box = tk.Text(container, height=10, state=tk.DISABLED)
        self.log_box.grid(column=0, row=2, sticky="nsew", pady=(10, 0))

        plot_frame = ttk.LabelFrame(container, text="Captured Voltages")
        plot_frame.grid(column=0, row=3, sticky="nsew", pady=(10, 0))
        self.figure, self.ax = plt.subplots(figsize=(5, 3))
        self.figure.subplots_adjust(left=0.12, right=0.97, bottom=0.18, top=0.9)
        self.ax.set_xlabel("Sample")
        self.ax.set_ylabel("Voltage (V)")
        self.ax.grid(True, linestyle="--", alpha=0.6)
        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def _log(self, message: str) -> None:
        if not self.log_box:
            return
        self.log_box.configure(state=tk.NORMAL)
        self.log_box.insert(tk.END, message + "\n")
        self.log_box.see(tk.END)
        self.log_box.configure(state=tk.DISABLED)

    def _on_session_change(self, session: Keithley2450Session) -> None:
        connected = session.inst is not None
        state = "normal" if connected else "disabled"
        self.btn_configure.configure(state=state)
        self.btn_output_off.configure(state=state)
        self.btn_auto.configure(state=state)
        if connected:
            try:
                session.ensure_script_from_path(self.SCRIPT_NAME, KEITHLEY_TSP_PATH)
            except Exception as exc:
                self._log(f"Script load failed: {exc}")

    def configure_meter(self) -> None:
        if self.session.inst is None:
            messagebox.showwarning("2450", "Connect first.")
            return
        try:
            range_arg = self._format_float(self.range_var.get(), default="2")
            nplc_arg = DEFAULT_MEASURE_NPLC
            self.session.write(f"configure_voltmeter({range_arg}, {nplc_arg})")
            self._log(f"Configured range={range_arg} V, NPLC={nplc_arg} (fixed).")
        except Exception as exc:
            messagebox.showerror("2450", str(exc))
            self._log(f"Configure failed: {exc}")

    def run_auto_trigger(self) -> None:
        self._run_auto_sequence(source="Manual", alert_user=True, skip_config=False)

    def start_auto_capture_from_trigger(self) -> None:
        self._run_auto_sequence(source="Trigger", alert_user=False, skip_config=True)

    def prepare_for_trigger_wait(self) -> bool:
        if self.session.inst is None:
            messagebox.showwarning("2450", "Connect first before arming wait.")
            return False
        try:
            range_arg, nplc_arg = self._configure_for_measurement()
        except Exception as exc:
            messagebox.showerror("2450", f"Unable to configure meter: {exc}")
            self._log(f"Pre-wait configure failed: {exc}")
            return False
        self._armed_for_trigger = True
        self._armed_range = range_arg
        self._armed_nplc = nplc_arg
        self._log(
            f"Armed measurement with range={range_arg} V, NPLC={nplc_arg} (defaults {DEFAULT_MEASURE_RANGE}/{DEFAULT_MEASURE_NPLC})."
        )
        return True

    def _run_auto_sequence(self, *, source: str, alert_user: bool, skip_config: bool) -> None:
        if self.session.inst is None:
            if alert_user:
                messagebox.showwarning(source, "Connect to the 2450 first.")
            return
        interval = FIXED_CAPTURE_INTERVAL_S
        try:
            count = int(float(self.auto_count_var.get()))
        except ValueError:
            if alert_user:
                messagebox.showerror(source, "Sample count must be numeric.")
            self._log(f"{source} auto capture aborted: invalid sample count.")
            return
        try:
            if skip_config and self._armed_for_trigger:
                range_arg = self._armed_range or DEFAULT_MEASURE_RANGE
                nplc_arg = self._armed_nplc or DEFAULT_MEASURE_NPLC
            else:
                range_arg, nplc_arg = self._configure_for_measurement()
            self._armed_for_trigger = False
        except Exception as exc:
            if alert_user:
                messagebox.showerror(source, str(exc))
            self._log(f"{source} auto setup failed: {exc}")
            self._armed_for_trigger = False
            return
        try:
            self._log(
                f"{source} auto: default range {DEFAULT_MEASURE_RANGE} V, {DEFAULT_MEASURE_NPLC} NPLC then applied {range_arg} / {nplc_arg}."
            )
            if source == "Trigger" and self.trigger_sync_callback:
                try:
                    self.trigger_sync_callback()
                except Exception as exc:
                    self._log(f"Sync callback failed: {exc}")
            lines = self._query_lines(
                f"print(auto_triggered_voltage_measurements({count}, {interval}))"
            )
        except Exception as exc:
            if alert_user:
                messagebox.showerror(source, str(exc))
            self._log(f"{source} auto trigger failed: {exc}")
            return
        label = f"{source} auto (interval={interval}s)"
        self._handle_sequence_result(lines, prefix=label)

    def _configure_for_measurement(self) -> tuple[str, str]:
        if self.session.inst is None:
            raise RuntimeError("Connect to the 2450 first.")
        default_range = DEFAULT_MEASURE_RANGE
        default_nplc = DEFAULT_MEASURE_NPLC
        self.session.write(f"configure_voltmeter({default_range}, {default_nplc})")
        range_arg = self._format_float(self.range_var.get(), default=default_range)
        nplc_arg = default_nplc
        self.session.write(f"configure_voltmeter({range_arg}, {nplc_arg})")
        return range_arg, nplc_arg

    def output_off(self) -> None:
        if self.session.inst is None:
            return
        try:
            self.session.write("smu.source.output = smu.OFF")
            self._log("Source output disabled.")
        except Exception as exc:
            self._log(f"Output off failed: {exc}")

    def _handle_sequence_result(self, lines: list[str], prefix: str) -> None:
        count_line, progress = self._split_numeric_tail(lines)
        for line in progress:
            self._log(line)
        captured = self._parse_count(count_line)
        count_display = str(captured) if captured is not None else (count_line or "unknown")
        self._log(f"{prefix} complete. Captured {count_display} reading(s).")
        self._fetch_and_plot_buffer()
        self._auto_shutdown_after_sequence()

    def _auto_shutdown_after_sequence(self) -> None:
        self.output_off()
        if self.shutdown_callback:
            try:
                self.shutdown_callback()
            except Exception as exc:
                self._log(f"Shutdown callback failed: {exc}")

    def _fetch_and_plot_buffer(self) -> None:
        if self.session.inst is None:
            return
        try:
            lines = self._query_lines("printbuffer(1, defbuffer1.n, defbuffer1)")
        except Exception as exc:
            self._log(f"Buffer read failed: {exc}")
            return
        buffer_text = "\n".join(lines)
        voltages = self._parse_buffer(buffer_text)
        if voltages:
            self._log("Captured voltages (V):")
            self._log(", ".join(f"{v:.6f}" for v in voltages))
        else:
            self._log("Buffer empty or parse error.")
        self._update_plot(voltages)

    def _query_lines(self, command: str) -> list[str]:
        inst = self.session.inst
        if inst is None:
            raise RuntimeError("Connect to the 2450 first.")
        inst.write(command)
        lines: list[str] = []
        original_timeout = inst.timeout
        try:
            first = inst.read().strip()
            if first:
                lines.append(first)
        except pyvisa.VisaIOError as exc:
            inst.timeout = original_timeout
            raise exc
        try:
            drain = min(original_timeout, self.DRAIN_TIMEOUT_MS)
            inst.timeout = drain
            while True:
                try:
                    extra = inst.read().strip()
                except pyvisa.VisaIOError as exc:
                    if exc.error_code == visa_constants.VI_ERROR_TMO:
                        break
                    raise
                if extra:
                    lines.append(extra)
        finally:
            inst.timeout = original_timeout
        return lines

    @staticmethod
    def _format_float(value: str, *, default: str = "nil") -> str:
        text = value.strip()
        if not text:
            return default
        float(text)
        return text

    @staticmethod
    def _split_numeric_tail(lines: list[str]) -> tuple[str | None, list[str]]:
        if not lines:
            return None, []
        for idx in range(len(lines) - 1, -1, -1):
            try:
                float(lines[idx])
                numeric = lines[idx]
                remainder = lines[:idx] + lines[idx + 1 :]
                return numeric, remainder
            except ValueError:
                continue
        return None, list(lines)

    @staticmethod
    def _parse_count(line: str | None) -> int | None:
        if line is None:
            return None
        try:
            value = float(line)
        except ValueError:
            return None
        return int(round(value))

    @staticmethod
    def _parse_buffer(text: str) -> list[float]:
        values: list[float] = []
        for token in text.replace("\n", ",").split(","):
            token = token.strip()
            if not token:
                continue
            try:
                values.append(float(token))
            except ValueError:
                continue
        return values

    def _update_plot(self, voltages: list[float]) -> None:
        if not self.ax or not self.canvas:
            return
        self.ax.clear()
        self.ax.set_xlabel("Sample")
        self.ax.set_ylabel("Voltage (V)")
        self.ax.grid(True, linestyle="--", alpha=0.6)
        if voltages:
            x_vals = list(range(1, len(voltages) + 1))
            self.ax.plot(x_vals, voltages, marker="o", markersize=4, linewidth=1.5, color="tab:blue")
            self.ax.fill_between(x_vals, voltages, color="tab:blue", alpha=0.15)
            self.ax.set_xlim(0.5, len(voltages) + 0.5)
        self.ax.set_title("Latest capture")
        self.canvas.draw_idle()


class Combined3021B2450App:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Tektronix AFG3021B Pulse + Keithley 2450 Voltage Capture")
        self.root.geometry("1600x900")
        self.root.minsize(1200, 750)

        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)
        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        left_frame = ttk.LabelFrame(main, text="Tektronix AFG3021B Control")
        left_frame.grid(column=0, row=0, sticky="nsew", padx=(0, 10))
        left_frame.rowconfigure(0, weight=1)
        left_frame.columnconfigure(0, weight=1)

        right_frame = ttk.Frame(main)
        right_frame.grid(column=1, row=0, sticky="nsew")
        right_frame.columnconfigure(0, weight=1)
        right_frame.rowconfigure(0, weight=0)
        right_frame.rowconfigure(1, weight=1)

        trigger_frame = ttk.LabelFrame(right_frame, text="Keithley 2450 Trigger Options")
        trigger_frame.grid(column=0, row=0, sticky="nsew")

        measure_frame = ttk.LabelFrame(right_frame, text="Keithley 2450 Measurements")
        measure_frame.grid(column=0, row=1, sticky="nsew", pady=(10, 0))

        self.tek_panel = Tek3021BPulsePanel(left_frame)
        self.session = Keithley2450Session()
        shared_address = tk.StringVar(value=DEFAULT_2450_ADDRESS)
        self.measure_panel = AsyncMeasurePanel(
            measure_frame,
            self.session,
            trigger_sync_callback=self.tek_panel.apply_gui_setup_for_trigger,
            shutdown_callback=self.tek_panel.output_off,
        )
        self.trigger_panel = TriggerOptionsPanel(
            trigger_frame,
            self.session,
            shared_address,
            trigger_callback=self.measure_panel.start_auto_capture_from_trigger,
            before_wait_callback=self.measure_panel.prepare_for_trigger_wait,
        )

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_close(self) -> None:
        try:
            self.measure_panel.output_off()
        except Exception:
            pass
        try:
            self.tek_panel.shutdown_outputs()
        except Exception:
            pass
        try:
            self.session.disconnect()
        except Exception:
            pass
        try:
            plt.close("all")
        except Exception:
            pass
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    Combined3021B2450App().run()


if __name__ == "__main__":
    main()
