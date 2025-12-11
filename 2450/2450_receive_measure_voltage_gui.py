"""GUI for loading the ReceiveMeasureVoltage TSP script and capturing voltages
from a Keithley 2450 when a digital trigger is detected.
"""

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
TSP_FILE = ROOT / "2450_receive_measure_voltage.tsp"
SCRIPT_NAME = "ReceiveMeasureVoltage"
DEFAULT_ADDRESS = "TCPIP0::169.254.188.69::5025::SOCKET"
DEFAULT_SAMPLES = "25"
DEFAULT_INTERVAL = "0.0"
DEFAULT_RANGE = "2"
DEFAULT_NPLC = "0.01"
DEFAULT_TIMEOUT = "10"
EDGE_OPTIONS = ("falling", "rising", "either")
LINE_NUMBER_OPTIONS = ("1", "2", "3", "4", "5", "6")
LINE_MODE_CHOICES = (
    ("Trigger input", "trigger_in"),
    ("Trigger open-drain", "trigger_open_drain"),
    ("Trigger output", "trigger_out"),
    ("Digital input", "digital_in"),
    ("Digital output", "digital_out"),
    ("Digital open-drain", "digital_open_drain"),
    ("Synchronous master", "synchronous_master"),
    ("Synchronous acceptor", "synchronous_acceptor"),
)
LINE_MODE_LABELS = tuple(label for label, _ in LINE_MODE_CHOICES)
LINE_MODE_LOOKUP = {label: key for label, key in LINE_MODE_CHOICES}
DRAIN_TIMEOUT_MS = 750


class TriggerMeasureGUI:
    """Tkinter GUI that waits for a trigger and then captures voltage samples."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("2450 Triggered Voltage Capture")
        self.root.minsize(1150, 720)

        self.rm: pyvisa.ResourceManager | None = None
        self.inst: pyvisa.resources.MessageBasedResource | None = None
        self.script_loaded = False

        self.address_var = tk.StringVar(value=DEFAULT_ADDRESS)
        self.samples_var = tk.StringVar(value=DEFAULT_SAMPLES)
        self.interval_var = tk.StringVar(value=DEFAULT_INTERVAL)
        self.range_var = tk.StringVar(value=DEFAULT_RANGE)
        self.nplc_var = tk.StringVar(value=DEFAULT_NPLC)
        self.timeout_var = tk.StringVar(value=DEFAULT_TIMEOUT)
        self.edge_var = tk.StringVar(value=EDGE_OPTIONS[0])
        self.line_var = tk.StringVar(value=LINE_NUMBER_OPTIONS[0])
        self.mode_var = tk.StringVar(value=LINE_MODE_LABELS[0])

        self.figure = None
        self.ax = None
        self.canvas = None

        self.log_text: scrolledtext.ScrolledText | None = None
        self.status_var = tk.StringVar(value="Disconnected")
        self.btn_clear: ttk.Button | None = None
        self.btn_errors: ttk.Button | None = None

        self.worker: threading.Thread | None = None
        self.running = False
        self.cancel_requested = False
        self.current_context: dict[str, str] | None = None

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------------ UI --
    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=3)
        self.root.columnconfigure(1, weight=4)
        self.root.rowconfigure(0, weight=1)

        control_frame = ttk.Frame(self.root, padding=12)
        control_frame.grid(column=0, row=0, sticky="nsew")
        control_frame.columnconfigure(1, weight=1)
        control_frame.rowconfigure(5, weight=1)

        plot_frame = ttk.Frame(self.root, padding=12)
        plot_frame.grid(column=1, row=0, sticky="nsew")
        plot_frame.columnconfigure(0, weight=1)
        plot_frame.rowconfigure(0, weight=1)

        # Connection row
        conn_row = ttk.Frame(control_frame)
        conn_row.grid(column=0, row=0, columnspan=2, sticky="ew")
        conn_row.columnconfigure(1, weight=1)
        ttk.Label(conn_row, text="VISA address:").grid(column=0, row=0, sticky="w", padx=(0, 6))
        ttk.Entry(conn_row, textvariable=self.address_var).grid(column=1, row=0, sticky="ew")
        ttk.Button(conn_row, text="Connect", command=self.connect).grid(column=2, row=0, padx=(8, 0))
        ttk.Button(conn_row, text="Disconnect", command=self.disconnect).grid(column=3, row=0, padx=(6, 0))

        # Measurement configuration
        meas_frame = ttk.LabelFrame(control_frame, text="Measurement setup")
        meas_frame.grid(column=0, row=1, columnspan=2, sticky="ew", pady=(12, 0))
        for col in range(4):
            meas_frame.columnconfigure(col, weight=1 if col % 2 == 1 else 0)

        ttk.Label(meas_frame, text="Samples").grid(column=0, row=0, sticky="w", padx=4, pady=(6, 0))
        ttk.Entry(meas_frame, textvariable=self.samples_var, width=10).grid(column=1, row=0, sticky="w", pady=(6, 0))
        ttk.Label(meas_frame, text="Spacing (s)").grid(column=2, row=0, sticky="w", padx=4, pady=(6, 0))
        ttk.Entry(meas_frame, textvariable=self.interval_var, width=10).grid(column=3, row=0, sticky="w", pady=(6, 0))

        ttk.Label(meas_frame, text="Range (V)").grid(column=0, row=1, sticky="w", padx=4, pady=(6, 0))
        ttk.Entry(meas_frame, textvariable=self.range_var, width=10).grid(column=1, row=1, sticky="w", pady=(6, 0))
        ttk.Label(meas_frame, text="NPLC").grid(column=2, row=1, sticky="w", padx=4, pady=(6, 0))
        ttk.Entry(meas_frame, textvariable=self.nplc_var, width=10).grid(column=3, row=1, sticky="w", pady=(6, 0))

        # Trigger configuration
        trig_frame = ttk.LabelFrame(control_frame, text="Trigger input")
        trig_frame.grid(column=0, row=2, columnspan=2, sticky="ew", pady=(12, 0))
        trig_frame.columnconfigure(1, weight=1)

        ttk.Label(trig_frame, text="Edge").grid(column=0, row=0, sticky="w", padx=4, pady=(6, 0))
        ttk.Combobox(trig_frame, textvariable=self.edge_var, state="readonly", values=EDGE_OPTIONS, width=12).grid(
            column=1, row=0, sticky="w", pady=(6, 0)
        )
        ttk.Label(trig_frame, text="DIGIO line").grid(column=0, row=1, sticky="w", padx=4, pady=(6, 0))
        ttk.Combobox(trig_frame, textvariable=self.line_var, state="readonly", values=LINE_NUMBER_OPTIONS, width=8).grid(
            column=1, row=1, sticky="w", pady=(6, 0)
        )
        ttk.Label(trig_frame, text="Line mode").grid(column=0, row=2, sticky="w", padx=4, pady=(6, 0))
        ttk.Combobox(trig_frame, textvariable=self.mode_var, state="readonly", values=LINE_MODE_LABELS, width=28).grid(
            column=1, row=2, sticky="w", pady=(6, 0)
        )
        ttk.Label(trig_frame, text="Timeout (s)").grid(column=0, row=3, sticky="w", padx=4, pady=(6, 6))
        ttk.Entry(trig_frame, textvariable=self.timeout_var, width=10).grid(column=1, row=3, sticky="w", pady=(6, 6))

        # Action buttons
        btn_row = ttk.Frame(control_frame)
        btn_row.grid(column=0, row=3, columnspan=2, sticky="ew", pady=(12, 0))
        btn_row.columnconfigure((0, 1, 2), weight=1)
        self.btn_start = ttk.Button(btn_row, text="Wait + Measure", command=self.start_measurement, state="disabled")
        self.btn_start.grid(column=0, row=0, padx=4)
        self.btn_cancel = ttk.Button(btn_row, text="Cancel", command=self.cancel_measurement, state="disabled")
        self.btn_cancel.grid(column=1, row=0, padx=4)
        self.btn_clear = ttk.Button(btn_row, text="Clear Display", command=self.clear_display, state="disabled")
        self.btn_clear.grid(column=2, row=0, padx=4)
        self.btn_errors = ttk.Button(btn_row, text="Read Errors", command=self.read_errors, state="disabled")
        self.btn_errors.grid(column=0, row=1, columnspan=3, pady=(8, 0))

        # Log output
        log_frame = ttk.LabelFrame(control_frame, text="Log")
        log_frame.grid(column=0, row=4, columnspan=2, sticky="nsew", pady=(12, 0))
        control_frame.rowconfigure(4, weight=1)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=16, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Status bar
        status = ttk.Frame(control_frame)
        status.grid(column=0, row=5, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Label(status, textvariable=self.status_var, anchor="w").pack(fill=tk.X)

        # Plot
        self.figure, self.ax = plt.subplots(figsize=(6, 4))
        self.figure.subplots_adjust(left=0.12, right=0.97, bottom=0.15, top=0.92)
        self.ax.set_xlabel("Sample")
        self.ax.set_ylabel("Voltage (V)")
        self.ax.grid(True, linestyle="--", alpha=0.6)
        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        self.canvas.get_tk_widget().grid(column=0, row=0, sticky="nsew")

    # --------------------------------------------------------------- connect --
    def connect(self) -> None:
        address = self.address_var.get().strip()
        if not address:
            messagebox.showerror("Connect", "Provide a VISA address.")
            return
        try:
            if self.rm is None:
                self.rm = pyvisa.ResourceManager()
            self.inst = self.rm.open_resource(address)
            self.inst.read_termination = "\n"
            self.inst.write_termination = "\n"
            self.inst.timeout = 20000
            idn = self.inst.query("*IDN?").strip()
            self._log(f"Connected: {idn}")
            self.status_var.set(f"Connected to {idn}")
            self._load_script()
            self._update_button_state()
        except pyvisa.VisaIOError as exc:
            messagebox.showerror("Connect", f"Connection failed: {exc}")
            self._log(f"Connection failed: {exc}")
            self.inst = None
            self._update_button_state()

    def disconnect(self) -> None:
        if self.running:
            self.cancel_measurement()
        if self.inst is not None:
            try:
                self.inst.close()
            except pyvisa.VisaIOError:
                pass
        if self.rm is not None:
            try:
                self.rm.close()
            except pyvisa.VisaIOError:
                pass
        self.rm = None
        self.inst = None
        self.script_loaded = False
        self.status_var.set("Disconnected")
        self._log("Disconnected.")
        self._update_button_state()

    # ---------------------------------------------------------------- script --
    def _load_script(self) -> None:
        if self.inst is None:
            return
        if not TSP_FILE.exists():
            messagebox.showerror("Script", f"Missing TSP file: {TSP_FILE}")
            return
        script_text = TSP_FILE.read_text(encoding="utf-8")
        try:
            self.inst.write(f"pcall(script.delete, '{SCRIPT_NAME}')")
        except pyvisa.VisaIOError:
            pass
        try:
            self.inst.write(f"loadscript {SCRIPT_NAME}")
            for line in script_text.splitlines():
                self.inst.write(line)
            self.inst.write("endscript")
            self.inst.write(f"{SCRIPT_NAME}.save()")
            self.inst.write(f"{SCRIPT_NAME}()")
            self.script_loaded = True
            self._log("TSP script loaded.")
        except pyvisa.VisaIOError as exc:
            messagebox.showerror("Script", f"Failed to load script: {exc}")
            self._log(f"Script load failed: {exc}")
            self.script_loaded = False

    # ------------------------------------------------------------- measure --
    def start_measurement(self) -> None:
        if not self._check_ready():
            return
        if self.running:
            messagebox.showinfo("Measure", "Measurement in progress.")
            return
        try:
            count = self._parse_int(self.samples_var.get(), minimum=1)
            interval_text = self.interval_var.get().strip()
            interval = 0.0 if not interval_text else self._parse_float(interval_text, minimum=0.0)
            range_arg = self._format_float_arg(self.range_var.get(), default=DEFAULT_RANGE)
            nplc_arg = self._format_float_arg(self.nplc_var.get(), default=DEFAULT_NPLC)
            timeout_arg = self._format_float_arg(self.timeout_var.get(), allow_nil=True)
            line = self._parse_int(self.line_var.get(), minimum=1, maximum=6)
            mode_key, mode_label = self._resolve_mode()
        except ValueError as exc:
            messagebox.showerror("Measure", str(exc))
            return

        edge = self.edge_var.get().strip().lower()
        edge_arg = f"'{edge}'" if edge else "nil"
        command = (
            "print(wait_for_trigger_measure("
            f"{count}, {interval}, {range_arg}, {nplc_arg}, {timeout_arg}, "
            f"{edge_arg}, {line}, '{mode_key}'"
            "))"
        )

        self.running = True
        self.cancel_requested = False
        self.current_context = {
            "line": f"DIGIO{line}",
            "edge": edge or "default",
            "mode": mode_label,
            "samples": str(count),
            "interval": f"{interval}",
        }
        self.status_var.set("Waiting for trigger...")
        self._log(
            "Waiting for trigger on {line} ({mode}, edge={edge}). Target: {samples} sample(s) @ interval {interval}s.".format(
                **self.current_context
            )
        )
        self._update_button_state()

        self.worker = threading.Thread(target=self._measurement_worker, args=(command,), daemon=True)
        self.worker.start()

    def cancel_measurement(self) -> None:
        if not self.running or self.inst is None:
            return
        self.cancel_requested = True
        try:
            self.inst.write("pcall(receive_measure_cancel)")
        except pyvisa.VisaIOError:
            pass
        try:
            self.inst.write("abort")
        except pyvisa.VisaIOError:
            pass
        self._log("Cancel requested.")

    def _measurement_worker(self, command: str) -> None:
        inst = self.inst
        if inst is None:
            self._async_complete(error="Instrument disconnected.")
            return
        try:
            lines = self._query_lines(command)
        except Exception as exc:  # pragma: no cover - GUI only
            self._async_complete(error=str(exc))
            return

        result_line = lines[-1] if lines else None
        progress_lines = lines[:-1] if len(lines) > 1 else []
        status = None
        captured = 0
        voltages: list[float] | None = None
        buffer_error: str | None = None

        if result_line is None:
            status = "NO_RESULT"
        else:
            normalized = result_line.strip().upper()
            if normalized in {"TIMEOUT", "INVALID_MODE", "CANCEL"}:
                status = normalized
            else:
                try:
                    captured = int(round(float(result_line)))
                    status = "COMPLETE"
                except ValueError:
                    status = result_line.strip() or "UNKNOWN"

        if status == "COMPLETE" and captured > 0:
            try:
                buffer_lines = self._query_lines("printbuffer(1, defbuffer1.n, defbuffer1)")
                buffer_text = "\n".join(buffer_lines)
                voltages = self._parse_buffer(buffer_text)
            except Exception as exc:  # pragma: no cover - GUI only
                buffer_error = str(exc)

        self._async_complete(
            success=status,
            captured=captured,
            progress=progress_lines,
            voltages=voltages,
            buffer_error=buffer_error,
        )

    def _async_complete(
        self,
        success: str | None = None,
        captured: int = 0,
        progress: list[str] | None = None,
        voltages: list[float] | None = None,
        buffer_error: str | None = None,
        error: str | None = None,
    ) -> None:
        def finish() -> None:
            self.running = False
            self.worker = None
            self._update_button_state()

            if progress:
                for line in progress:
                    self._log(line)

            if error:
                self._log(f"Measurement failed: {error}")
                messagebox.showerror("Measure", error)
                self.status_var.set("Measurement failed")
                return

            if success == "TIMEOUT":
                self._log("No trigger detected before timeout.")
                self.status_var.set("Timeout waiting for trigger")
                return
            if success == "INVALID_MODE":
                self._log("Selected DIGIO line mode is not a trigger input.")
                self.status_var.set("Invalid mode for trigger input")
                return
            if success == "CANCEL":
                self._log("Measurement cancelled.")
                self.status_var.set("Cancelled")
                return
            if success not in {"COMPLETE", "NO_RESULT"}:
                self._log(f"Instrument returned: {success}")
                self.status_var.set(success or "Unknown result")
                return

            self._log(f"Captured {captured} sample(s).")
            self.status_var.set("Measurement complete")
            if buffer_error:
                self._log(f"Buffer read failed: {buffer_error}")
            elif voltages is not None:
                if voltages:
                    self._log("Voltages (V):")
                    self._log(", ".join(f"{v:.6f}" for v in voltages))
                else:
                    self._log("Buffer empty.")
                self._update_plot(voltages)

        self.root.after(0, finish)

    # --------------------------------------------------------------- actions --
    def clear_display(self) -> None:
        if self.inst is None:
            return
        try:
            self.inst.write("display.clear()")
            self._log("Display cleared.")
        except pyvisa.VisaIOError as exc:
            self._log(f"Clear display failed: {exc}")

    def read_errors(self) -> None:
        if self.inst is None:
            messagebox.showwarning("Errors", "Instrument not connected.")
            return
        try:
            errors: list[str] = []
            for _ in range(10):
                err = self.inst.query("SYST:ERR?").strip()
                errors.append(err)
                if err.startswith("0,"):
                    break
            self._log("Errors: " + " | ".join(errors))
        except pyvisa.VisaIOError as exc:
            messagebox.showerror("Errors", f"Failed to read errors: {exc}")

    # ----------------------------------------------------------------- utils --
    def _log(self, message: str) -> None:
        if not self.log_text:
            return
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _check_ready(self) -> bool:
        if self.inst is None:
            messagebox.showwarning("Instrument", "Connect to the instrument first.")
            return False
        if not self.script_loaded:
            self._load_script()
        return self.script_loaded

    def _update_button_state(self) -> None:
        connected = self.inst is not None
        can_run = connected and not self.running
        self.btn_start.configure(state="normal" if can_run else "disabled")
        self.btn_cancel.configure(state="normal" if connected and self.running else "disabled")
        if self.btn_clear is not None:
            self.btn_clear.configure(state="normal" if can_run else "disabled")
        if self.btn_errors is not None:
            self.btn_errors.configure(state="normal" if can_run else "disabled")

    def _parse_int(self, value: str, *, minimum: int | None = None, maximum: int | None = None) -> int:
        try:
            ivalue = int(float(value.strip()))
        except ValueError as exc:
            raise ValueError("Enter a numeric value.") from exc
        if minimum is not None and ivalue < minimum:
            raise ValueError(f"Value must be >= {minimum}.")
        if maximum is not None and ivalue > maximum:
            raise ValueError(f"Value must be <= {maximum}.")
        return ivalue

    def _parse_float(self, value: str, *, minimum: float | None = None) -> float:
        try:
            fvalue = float(value.strip())
        except ValueError as exc:
            raise ValueError("Enter a numeric value.") from exc
        if minimum is not None and fvalue < minimum:
            raise ValueError(f"Value must be >= {minimum}.")
        return fvalue

    def _format_float_arg(
        self,
        value: str,
        *,
        default: str | None = None,
        allow_nil: bool = False,
    ) -> str:
        text = value.strip()
        if not text:
            if allow_nil:
                return "nil"
            if default is not None:
                return default
            raise ValueError("Enter a numeric value.")
        try:
            float(text)
        except ValueError as exc:
            raise ValueError(f"Invalid numeric value: {value}") from exc
        return text

    def _resolve_mode(self) -> tuple[str, str]:
        label = self.mode_var.get()
        key = LINE_MODE_LOOKUP.get(label)
        if not key:
            raise ValueError("Select a valid line mode.")
        return key, label

    def _query_lines(self, command: str) -> list[str]:
        inst = self.inst
        if inst is None:
            raise RuntimeError("Instrument not connected.")
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
            inst.timeout = min(original_timeout, DRAIN_TIMEOUT_MS)
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

    def _parse_buffer(self, text: str) -> list[float]:
        if not text:
            return []
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

    def _update_plot(self, voltages: list[float] | None) -> None:
        if self.ax is None or self.canvas is None:
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
        self.ax.set_title("Triggered capture")
        self.canvas.draw_idle()

    # ----------------------------------------------------------------- close --
    def on_close(self) -> None:
        try:
            self.disconnect()
        finally:
            if self.figure:
                plt.close(self.figure)
            self.root.destroy()


def main() -> None:
    root = tk.Tk()
    TriggerMeasureGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
