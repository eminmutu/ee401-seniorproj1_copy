"""Tkinter GUI for running the triggered_measure_once helper in
2450_triggered_measure_voltage.tsp on a Keithley 2450."""

from __future__ import annotations

from datetime import datetime
import pathlib
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import pyvisa
from pyvisa.resources import MessageBasedResource
from pyvisa import constants as visa_constants

ROOT = pathlib.Path(__file__).resolve().parent
TSP_SCRIPT_PATH = ROOT / "2450_triggered_measure_voltage.tsp"
SCRIPT_NAME = "TriggeredMeasure"
DEFAULT_ADDRESS = "TCPIP0::169.254.188.69::5025::SOCKET"
DEFAULT_RANGE = "2"
DEFAULT_TIMEOUT = "10"
EDGE_CHOICES = ("rising", "falling", "either")
LINE_CHOICES = ("1", "2", "3", "4", "5", "6")
SENTINEL_DONE_PREFIX = "$MEAS:DONE$"
SENTINEL_TIMEOUT = "$MEAS:TIMEOUT$"
READ_DRAIN_TIMEOUT_MS = 750


class TriggeredMeasureApp:
    """Simple GUI to wait for a digital trigger and capture one voltage."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("2450 Triggered Measure")
        self.root.minsize(700, 420)

        self.rm: pyvisa.ResourceManager | None = None
        self.inst: MessageBasedResource | None = None
        self.script_loaded = False

        self.address_var = tk.StringVar(value=DEFAULT_ADDRESS)
        self.range_var = tk.StringVar(value=DEFAULT_RANGE)
        self.edge_var = tk.StringVar(value=EDGE_CHOICES[0])
        self.line_var = tk.StringVar(value=LINE_CHOICES[0])
        self.timeout_var = tk.StringVar(value=DEFAULT_TIMEOUT)
        self.force_output_var = tk.BooleanVar(value=True)

        self.status_var = tk.StringVar(value="Disconnected")
        self.result_var = tk.StringVar(value="No measurement yet")
        self.result_details_var = tk.StringVar(value="Line -, Edge -, Range - V")

        self.figure: plt.Figure | None = None
        self.ax = None
        self.canvas: FigureCanvasTkAgg | None = None
        self.btn_clear_plot: ttk.Button | None = None
        self.measurements: list[float] = []

        self.log_widget: scrolledtext.ScrolledText | None = None
        self.worker: threading.Thread | None = None
        self.running = False
        self.cancel_requested = False
        self._output_restore: float | None = None
        self._pending_context: dict[str, str] | None = None

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=2)
        self.root.columnconfigure(1, weight=3)
        self.root.rowconfigure(0, weight=1)

        control = ttk.Frame(self.root, padding=12)
        control.grid(column=0, row=0, sticky="nsew")
        control.columnconfigure(0, weight=1)
        control.rowconfigure(4, weight=1)

        plot_container = ttk.Frame(self.root, padding=12)
        plot_container.grid(column=1, row=0, sticky="nsew")
        plot_container.columnconfigure(0, weight=1)
        plot_container.rowconfigure(1, weight=1)

        conn = ttk.LabelFrame(control, text="Instrument")
        conn.grid(column=0, row=0, sticky="ew")
        conn.columnconfigure(1, weight=1)

        ttk.Label(conn, text="VISA address:").grid(column=0, row=0, sticky="w", padx=(0, 6), pady=6)
        ttk.Entry(conn, textvariable=self.address_var).grid(column=1, row=0, sticky="ew", pady=6)
        ttk.Button(conn, text="Connect", command=self.connect).grid(column=2, row=0, padx=(8, 0))
        ttk.Button(conn, text="Disconnect", command=self.disconnect).grid(column=3, row=0, padx=(6, 0))

        meas = ttk.LabelFrame(control, text="Measurement")
        meas.grid(column=0, row=1, sticky="ew", pady=(12, 0))
        for col in range(4):
            meas.columnconfigure(col, weight=1 if col % 2 == 1 else 0)

        ttk.Label(meas, text="Range (V)").grid(column=0, row=0, sticky="w", padx=(0, 6), pady=(8, 0))
        ttk.Entry(meas, textvariable=self.range_var, width=12).grid(column=1, row=0, sticky="w", pady=(8, 0))
        ttk.Label(meas, text="Timeout (s)").grid(column=2, row=0, sticky="w", padx=(0, 6), pady=(8, 0))
        ttk.Entry(meas, textvariable=self.timeout_var, width=12).grid(column=3, row=0, sticky="w", pady=(8, 0))

        ttk.Label(meas, text="Edge").grid(column=0, row=1, sticky="w", padx=(0, 6), pady=(8, 8))
        ttk.Combobox(meas, textvariable=self.edge_var, state="readonly", values=EDGE_CHOICES, width=10).grid(
            column=1, row=1, sticky="w", pady=(8, 8)
        )
        ttk.Label(meas, text="DIGIO line").grid(column=2, row=1, sticky="w", padx=(0, 6), pady=(8, 8))
        ttk.Combobox(meas, textvariable=self.line_var, state="readonly", values=LINE_CHOICES, width=10).grid(
            column=3, row=1, sticky="w", pady=(8, 8)
        )
        ttk.Checkbutton(
            meas,
            text="Force source output ON during measurement",
            variable=self.force_output_var,
        ).grid(column=0, row=2, columnspan=4, sticky="w", pady=(0, 8))

        result = ttk.LabelFrame(control, text="Latest reading")
        result.grid(column=0, row=2, sticky="ew", pady=(12, 0))
        ttk.Label(result, textvariable=self.result_var, font=("Segoe UI", 14, "bold"), anchor="center").pack(
            fill=tk.X, padx=8, pady=8
        )
        ttk.Label(result, textvariable=self.result_details_var, anchor="center").pack(padx=8, pady=(0, 8))

        actions = ttk.Frame(control)
        actions.grid(column=0, row=3, sticky="ew", pady=(12, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        actions.columnconfigure(2, weight=1)
        actions.columnconfigure(3, weight=1)
        self.btn_start = ttk.Button(actions, text="Wait + Measure", command=self.start_measurement, state=tk.DISABLED)
        self.btn_start.grid(column=0, row=0, padx=4)
        self.btn_cancel = ttk.Button(actions, text="Cancel", command=self.cancel_measurement, state=tk.DISABLED)
        self.btn_cancel.grid(column=1, row=0, padx=4)
        ttk.Button(actions, text="Clear Log", command=self.clear_log).grid(column=2, row=0, padx=4)
        self.btn_clear_plot = ttk.Button(actions, text="Clear Plot", command=self.clear_plot, state=tk.DISABLED)
        self.btn_clear_plot.grid(column=3, row=0, padx=4)

        log = ttk.LabelFrame(control, text="Log")
        log.grid(column=0, row=4, sticky="nsew", pady=(12, 0))
        self.log_widget = scrolledtext.ScrolledText(log, height=10, state=tk.DISABLED)
        self.log_widget.pack(fill=tk.BOTH, expand=True)

        status = ttk.Frame(control)
        status.grid(column=0, row=5, sticky="ew", pady=(12, 0))
        ttk.Label(status, textvariable=self.status_var, anchor="w").pack(fill=tk.X)

        ttk.Label(plot_container, text="Triggered measurement history", font=("Segoe UI", 12, "bold")).grid(
            column=0, row=0, sticky="w"
        )
        plot_frame = ttk.LabelFrame(plot_container, text="Voltage vs. trigger")
        plot_frame.grid(column=0, row=1, sticky="nsew", pady=(8, 0))
        plot_container.rowconfigure(1, weight=1)

        self.figure, self.ax = plt.subplots(figsize=(5.5, 4))
        self.figure.subplots_adjust(left=0.12, right=0.95, bottom=0.15, top=0.92)
        self.ax.set_xlabel("Measurement #")
        self.ax.set_ylabel("Voltage (V)")
        self.ax.grid(True, linestyle="--", alpha=0.6)
        self.ax.set_title("Awaiting data")
        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self._refresh_plot()

    def connect(self) -> None:
        address = self.address_var.get().strip()
        if not address:
            messagebox.showerror("Connect", "Provide a VISA resource address.")
            return
        try:
            if self.rm is None:
                self.rm = pyvisa.ResourceManager()
            self.inst = self.rm.open_resource(address)
            self.inst.read_termination = "\n"
            self.inst.write_termination = "\n"
            self.inst.timeout = 60000
            idn = self.inst.query("*IDN?").strip()
            self.status_var.set(f"Connected: {idn}")
            self._log(f"Connected to {idn}")
            self._load_script()
            self._update_buttons()
        except pyvisa.VisaIOError as exc:
            messagebox.showerror("Connect", f"Failed to connect: {exc}")
            self._log(f"Connection failed: {exc}")
            self.inst = None
            self._update_buttons()

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
        self._output_restore = None
        self._pending_context = None
        self.status_var.set("Disconnected")
        self.result_var.set("No measurement yet")
        self.result_details_var.set("Line -, Edge -, Range - V")
        self._log("Disconnected.")
        self._update_buttons()

    def _load_script(self) -> None:
        if self.inst is None:
            return
        if not TSP_SCRIPT_PATH.exists():
            messagebox.showerror("Script", f"Missing TSP file: {TSP_SCRIPT_PATH}")
            self._log(f"TSP file not found: {TSP_SCRIPT_PATH}")
            return
        try:
            script_text = TSP_SCRIPT_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Script", f"Failed to read TSP file: {exc}")
            self._log(f"TSP read failed: {exc}")
            return
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

    def start_measurement(self) -> None:
        if not self._check_ready():
            return
        if self.running:
            messagebox.showinfo("Measure", "Measurement already running.")
            return
        try:
            range_value = self._parse_float(self.range_var.get(), "Range", minimum=1e-6)
            timeout_value = self._parse_float(self.timeout_var.get(), "Timeout", minimum=0.0)
            edge = self.edge_var.get().strip().lower()
            line = self._parse_int(self.line_var.get(), "DIGIO line", minimum=1, maximum=6)
        except ValueError as exc:
            messagebox.showerror("Parameters", str(exc))
            return

        range_arg = f"{range_value:.9g}"
        timeout_arg = f"{timeout_value:.9g}"
        command = (
            "print(triggered_measure_once("
            f"{range_arg}, '{edge}', {line}, {timeout_arg}"
            "))"
        )

        try:
            self._ensure_output_ready()
        except (pyvisa.VisaIOError, RuntimeError) as exc:
            messagebox.showerror("Measure", f"Failed to set output state: {exc}")
            self._log(f"Failed to configure output state: {exc}")
            return

        self.running = True
        self.cancel_requested = False
        self._pending_context = {
            "line": f"DIGIO{line}",
            "edge": edge or "default",
            "range": f"{range_value:.6g}",
        }
        self._update_details()
        self.status_var.set("Waiting for trigger...")
        self._log(
            f"Waiting for trigger on DIGIO{line} ({edge} edge, range {range_value} V, timeout {timeout_value} s)"
        )
        self._update_buttons()

        self.worker = threading.Thread(target=self._measurement_worker, args=(command,), daemon=True)
        self.worker.start()

    def cancel_measurement(self) -> None:
        if not self.running or self.inst is None:
            return
        self.cancel_requested = True
        try:
            self.inst.write("abort")
        except pyvisa.VisaIOError:
            pass
        self._log("Cancel requested...")

    def _measurement_worker(self, command: str) -> None:
        if self.inst is None:
            self._async_finish(error="Instrument disconnected.")
            return
        try:
            lines = self._query_lines(command)
        except Exception as exc:  # pragma: no cover - GUI interaction
            self._async_finish(error=str(exc))
            return

        stripped_lines = [line.rstrip() for line in lines if line.strip()]
        if not stripped_lines:
            self._async_finish(error="Instrument returned no data.")
            return
        sentinel_measurement: float | None = None
        status_hint: str | None = None
        ordered_lines: list[tuple[str, bool]] = []  # (text, is_sentinel)
        for line in stripped_lines:
            sentinel = self._parse_measurement_sentinel(line)
            if sentinel is not None:
                status_hint, value = sentinel
                if value is not None:
                    sentinel_measurement = value
                ordered_lines.append((line, True))
                continue
            ordered_lines.append((line, False))

        result_index: int | None = None
        for idx in range(len(ordered_lines) - 1, -1, -1):
            if not ordered_lines[idx][1]:
                result_index = idx
                break
        result_line = ordered_lines[result_index][0] if result_index is not None else ""

        progress: list[str] = []
        for idx, (text, _) in enumerate(ordered_lines):
            if result_index is not None and idx == result_index:
                continue
            progress.append(text)

        measurement: float | None = None
        if result_line:
            if result_line.lower() != "nil":
                try:
                    measurement = float(result_line)
                except ValueError:
                    progress.append(result_line)
                    result_line = ""
            else:
                result_line = ""

        if measurement is None and sentinel_measurement is not None:
            measurement = sentinel_measurement

        buffer_value = self._read_latest_from_buffer()
        self._async_finish(
            progress=progress,
            measurement=measurement,
            buffer_value=buffer_value,
            status_hint=status_hint,
        )

    def _async_finish(
        self,
        *,
        progress: list[str] | None = None,
        measurement: float | None = None,
        error: str | None = None,
        buffer_value: float | None = None,
        status_hint: str | None = None,
    ) -> None:
        def finalize() -> None:
            self.running = False
            self.worker = None
            self._update_buttons()

            if progress:
                for line in progress:
                    self._log(line)

            self._restore_output_state()

            if error:
                self.status_var.set("Measurement failed")
                self._log(f"Measurement failed: {error}")
                self._pending_context = None
                self._update_details()
                messagebox.showerror("Measure", error)
                return

            latest_value = buffer_value if buffer_value is not None else measurement

            if latest_value is None:
                if self.cancel_requested:
                    self.status_var.set("Cancelled")
                    self._log("Measurement cancelled.")
                else:
                    if status_hint == "timeout":
                        self.status_var.set("Trigger timeout")
                        self._log("No trigger detected before timeout.")
                    else:
                        self.status_var.set("No measurement")
                        self._log("No measurement returned by script.")
                    self.result_var.set("No measurement")
                self._update_details()
                self._pending_context = None
                return

            self.status_var.set("Measurement complete")
            if measurement is None and buffer_value is not None:
                self._log("Using latest defbuffer1 reading for display.")
            display_value = latest_value
            self.measurements.append(display_value)
            self.result_var.set(f"{display_value:.9f} V")
            self._log(f"Triggered voltage: {display_value:.9f} V")
            self._update_details(display_value)
            if self.btn_clear_plot is not None:
                self.btn_clear_plot.configure(state=tk.NORMAL)
            self._pending_context = None

        self.root.after(0, finalize)

    def _parse_float(self, text: str, label: str, *, minimum: float | None = None) -> float:
        stripped = text.strip()
        if not stripped:
            raise ValueError(f"{label} must not be empty.")
        try:
            value = float(stripped)
        except ValueError as exc:
            raise ValueError(f"{label} must be a number.") from exc
        if minimum is not None and value < minimum:
            raise ValueError(f"{label} must be >= {minimum}.")
        return value

    def _parse_int(self, text: str, label: str, *, minimum: int, maximum: int) -> int:
        stripped = text.strip()
        if not stripped:
            raise ValueError(f"{label} must not be empty.")
        try:
            value = int(float(stripped))
        except ValueError as exc:
            raise ValueError(f"{label} must be an integer.") from exc
        if value < minimum or value > maximum:
            raise ValueError(f"{label} must be between {minimum} and {maximum}.")
        return value

    def _check_ready(self) -> bool:
        if self.inst is None:
            messagebox.showerror("Measure", "Connect to the instrument first.")
            return False
        if not self.script_loaded:
            self._load_script()
            if not self.script_loaded:
                return False
        return True

    def _update_buttons(self) -> None:
        connected = self.inst is not None
        self.btn_start.configure(state=tk.NORMAL if connected and not self.running else tk.DISABLED)
        self.btn_cancel.configure(state=tk.NORMAL if self.running else tk.DISABLED)
        if self.btn_clear_plot is not None:
            self.btn_clear_plot.configure(state=tk.NORMAL if self.measurements else tk.DISABLED)

    def clear_log(self) -> None:
        if self.log_widget is None:
            return
        self.log_widget.configure(state=tk.NORMAL)
        self.log_widget.delete("1.0", tk.END)
        self.log_widget.configure(state=tk.DISABLED)

    def clear_plot(self) -> None:
        self.measurements.clear()
        self._refresh_plot()
        if self.btn_clear_plot is not None:
            self.btn_clear_plot.configure(state=tk.DISABLED)

    def _ensure_output_ready(self) -> None:
        self._output_restore = None
        if not self.force_output_var.get() or self.inst is None:
            return
        state = self._query_float("print(smu.source.output)")
        if state <= 0.5:
            self.inst.write("smu.source.output = smu.ON")
            self._output_restore = state
            self._log("Source output enabled for measurement.")

    def _restore_output_state(self) -> None:
        if self._output_restore is None or self.inst is None:
            return
        if self._output_restore <= 0.5:
            try:
                self.inst.write("smu.source.output = smu.OFF")
                self._log("Source output restored to OFF.")
            except pyvisa.VisaIOError:
                self._log("Failed to restore source output state.")
        self._output_restore = None

    def _query_float(self, command: str) -> float:
        if self.inst is None:
            raise RuntimeError("Instrument not connected.")
        response = self.inst.query(command).strip()
        if not response:
            raise RuntimeError("Instrument returned no data.")

        normalized = response.lower()
        if "off" in normalized:
            return 0.0
        if "on" in normalized:
            return 1.0

        try:
            return float(response)
        except ValueError as exc:
            raise RuntimeError(f"Unexpected response: {response}") from exc

    def _parse_measurement_sentinel(self, line: str) -> tuple[str, float | None] | None:
        if line.startswith(SENTINEL_DONE_PREFIX):
            value_text = line[len(SENTINEL_DONE_PREFIX):].strip()
            try:
                value = float(value_text)
            except ValueError:
                value = None
            return "done", value
        if line.startswith(SENTINEL_TIMEOUT):
            return "timeout", None
        return None

    def _read_latest_from_buffer(self) -> float | None:
        try:
            lines = self._query_lines("printbuffer(1, defbuffer1.n, defbuffer1)")
        except Exception as exc:
            self._log(f"Buffer read failed: {exc}")
            return None
        if not lines:
            return None
        values = self._parse_buffer("\n".join(lines))
        if not values:
            return None
        return values[-1]

    def _query_lines(self, command: str) -> list[str]:
        if self.inst is None:
            raise RuntimeError("Instrument not connected.")
        inst = self.inst
        inst.write(command)
        original_timeout = inst.timeout
        lines: list[str] = []
        try:
            first = inst.read().strip()
            if first:
                lines.append(first)
        except pyvisa.VisaIOError as exc:
            inst.timeout = original_timeout
            raise exc
        try:
            inst.timeout = min(original_timeout, READ_DRAIN_TIMEOUT_MS)
            while True:
                try:
                    chunk = inst.read().strip()
                except pyvisa.VisaIOError as exc:
                    if exc.error_code == visa_constants.VI_ERROR_TMO:
                        break
                    raise
                if not chunk:
                    continue
                lines.append(chunk)
        finally:
            inst.timeout = original_timeout
        return lines

    @staticmethod
    def _parse_buffer(text: str) -> list[float]:
        values: list[float] = []
        for token in text.replace("\n", ",").split(","):
            stripped = token.strip()
            if not stripped:
                continue
            try:
                values.append(float(stripped))
            except ValueError:
                continue
        return values

    def _update_details(self, measurement: float | None = None) -> None:
        context = self._pending_context
        if context is None:
            if measurement is None:
                self.result_details_var.set("Line -, Edge -, Range - V")
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        detail = (
            f"{context.get('line', 'DIGIO-')} | edge {context.get('edge', '?')} | "
            f"range {context.get('range', '-')} V | {timestamp}"
        )
        if measurement is not None:
            detail += f" | last {measurement:.6g} V"
        self.result_details_var.set(detail)
        self._refresh_plot()

    def _refresh_plot(self) -> None:
        if self.ax is None or self.canvas is None:
            return
        self.ax.clear()
        self.ax.set_xlabel("Measurement #")
        self.ax.set_ylabel("Voltage (V)")
        self.ax.grid(True, linestyle="--", alpha=0.6)
        if self.measurements:
            x_vals = list(range(1, len(self.measurements) + 1))
            self.ax.plot(
                x_vals,
                self.measurements,
                marker="o",
                markersize=4,
                linewidth=1.5,
                color="tab:blue",
            )
            self.ax.fill_between(x_vals, self.measurements, color="tab:blue", alpha=0.2)
            self.ax.set_xlim(0.5, len(self.measurements) + 0.5)
            self.ax.set_title("Triggered measurements")
        else:
            self.ax.set_title("Awaiting data")
        self.canvas.draw_idle()

    def _log(self, message: str) -> None:
        if self.log_widget is None:
            return
        self.log_widget.configure(state=tk.NORMAL)
        self.log_widget.insert(tk.END, message + "\n")
        self.log_widget.see(tk.END)
        self.log_widget.configure(state=tk.DISABLED)

    def on_close(self) -> None:
        try:
            self.disconnect()
        finally:
            if self.figure is not None:
                plt.close(self.figure)
            self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = TriggeredMeasureApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
