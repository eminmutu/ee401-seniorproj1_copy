"""GUI to run the run_fast_external_trigger() helper on a Keithley 2450.

This interface lets you connect to the instrument, load the
`2450_triggered_different_measure_voltage.tsp` script, and invoke the
`run_fast_external_trigger` function with custom parameters (including NPLC).
Captured
voltages are displayed in the log as well as plotted on a simple chart.
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
from pyvisa.resources import MessageBasedResource

ROOT = pathlib.Path(__file__).resolve().parent
TSP_SOURCE = ROOT / "2450_triggered_different_measure_voltage.tsp"
SCRIPT_NAME = "FastExternalTrigger"
DEFAULT_ADDRESS = "TCPIP0::169.254.188.69::5025::SOCKET"
EDGE_CHOICES = ("rising", "falling", "either")
READ_DRAIN_TIMEOUT_MS = 750


class ExternalTriggerGUI:
    """Tkinter GUI that wraps run_fast_external_trigger."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("2450 External Trigger Capture")
        self.root.minsize(900, 520)

        self.rm: pyvisa.ResourceManager | None = None
        self.inst: MessageBasedResource | None = None
        self.script_loaded = False

        self.address_var = tk.StringVar(value=DEFAULT_ADDRESS)
        self.measure_count_var = tk.StringVar(value="20")
        self.source_current_var = tk.StringVar(value="0.01")
        self.source_range_var = tk.StringVar(value="0.01")
        self.measure_range_var = tk.StringVar(value="2")
        self.nplc_var = tk.StringVar(value="0.01")
        self.trig_line_var = tk.StringVar(value="1")
        self.trig_edge_var = tk.StringVar(value=EDGE_CHOICES[0])

        self.status_var = tk.StringVar(value="Disconnected")
        self.result_var = tk.StringVar(value="No run yet")

        self.log_widget: scrolledtext.ScrolledText | None = None
        self.figure: plt.Figure | None = None
        self.ax = None
        self.canvas: FigureCanvasTkAgg | None = None
        self.btn_run: ttk.Button | None = None
        self.btn_cancel: ttk.Button | None = None

        self.worker: threading.Thread | None = None
        self.running = False
        self.cancel_requested = False
        self.latest_data: list[tuple[int, float]] = []

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------------ UI --
    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=2)
        self.root.columnconfigure(1, weight=3)
        self.root.rowconfigure(0, weight=1)

        control = ttk.Frame(self.root, padding=12)
        control.grid(column=0, row=0, sticky="nsew")
        control.columnconfigure(1, weight=1)

        plot_container = ttk.Frame(self.root, padding=12)
        plot_container.grid(column=1, row=0, sticky="nsew")
        plot_container.columnconfigure(0, weight=1)
        plot_container.rowconfigure(1, weight=1)

        conn = ttk.LabelFrame(control, text="Instrument")
        conn.grid(column=0, row=0, columnspan=2, sticky="ew")
        conn.columnconfigure(1, weight=1)
        ttk.Label(conn, text="VISA address:").grid(column=0, row=0, sticky="w", padx=(0, 6), pady=6)
        ttk.Entry(conn, textvariable=self.address_var).grid(column=1, row=0, sticky="ew", pady=6)
        ttk.Button(conn, text="Connect", command=self.connect).grid(column=2, row=0, padx=(8, 0))
        ttk.Button(conn, text="Disconnect", command=self.disconnect).grid(column=3, row=0, padx=(6, 0))

        params = ttk.LabelFrame(control, text="run_fast_external_trigger parameters")
        params.grid(column=0, row=1, columnspan=2, sticky="ew", pady=(12, 0))
        for col in range(4):
            params.columnconfigure(col, weight=1 if col % 2 == 1 else 0)

        ttk.Label(params, text="Samples (count)").grid(column=0, row=0, sticky="w", padx=(0, 6), pady=(8, 0))
        ttk.Entry(params, textvariable=self.measure_count_var, width=12).grid(column=1, row=0, sticky="w", pady=(8, 0))

        ttk.Label(params, text="Source current (A)").grid(column=0, row=1, sticky="w", padx=(0, 6), pady=(8, 0))
        ttk.Entry(params, textvariable=self.source_current_var, width=12).grid(column=1, row=1, sticky="w", pady=(8, 0))

        ttk.Label(params, text="Source range (A)").grid(column=0, row=2, sticky="w", padx=(0, 6), pady=(8, 0))
        ttk.Entry(params, textvariable=self.source_range_var, width=12).grid(column=1, row=2, sticky="w", pady=(8, 0))

        ttk.Label(params, text="Measure range (V)").grid(column=0, row=3, sticky="w", padx=(0, 6), pady=(8, 0))
        ttk.Entry(params, textvariable=self.measure_range_var, width=12).grid(column=1, row=3, sticky="w", pady=(8, 0))

        ttk.Label(params, text="NPLC").grid(column=0, row=4, sticky="w", padx=(0, 6), pady=(8, 0))
        ttk.Entry(params, textvariable=self.nplc_var, width=12).grid(column=1, row=4, sticky="w", pady=(8, 0))

        ttk.Label(params, text="DIGIO line (1-6)").grid(column=2, row=0, sticky="w", padx=(12, 6), pady=(8, 0))
        ttk.Entry(params, textvariable=self.trig_line_var, width=6).grid(column=3, row=0, sticky="w", pady=(8, 0))

        ttk.Label(params, text="Edge").grid(column=2, row=1, sticky="w", padx=(12, 6), pady=(8, 0))
        ttk.Combobox(params, textvariable=self.trig_edge_var, state="readonly", values=EDGE_CHOICES, width=10).grid(
            column=3, row=1, sticky="w", pady=(8, 0)
        )

        ttk.Label(params, text="Result").grid(column=2, row=2, sticky="w", padx=(12, 6), pady=(8, 0))
        ttk.Label(params, textvariable=self.result_var, foreground="navy").grid(column=3, row=2, sticky="w", pady=(8, 0))

        actions = ttk.Frame(control)
        actions.grid(column=0, row=2, columnspan=2, sticky="ew", pady=(12, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        actions.columnconfigure(2, weight=1)
        self.btn_run = ttk.Button(actions, text="Run Sequence", command=self.start_measurement, state=tk.DISABLED)
        self.btn_run.grid(column=0, row=0, padx=4)
        self.btn_cancel = ttk.Button(actions, text="Cancel", command=self.cancel_measurement, state=tk.DISABLED)
        self.btn_cancel.grid(column=1, row=0, padx=4)
        ttk.Button(actions, text="Clear Log", command=self.clear_log).grid(column=2, row=0, padx=4)

        log = ttk.LabelFrame(control, text="Log")
        log.grid(column=0, row=3, columnspan=2, sticky="nsew", pady=(12, 0))
        control.rowconfigure(3, weight=1)
        self.log_widget = scrolledtext.ScrolledText(log, height=12, state=tk.DISABLED)
        self.log_widget.pack(fill=tk.BOTH, expand=True)

        status = ttk.Frame(control)
        status.grid(column=0, row=4, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Label(status, textvariable=self.status_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Label(plot_container, text="Captured voltages", font=("Segoe UI", 12, "bold")).grid(column=0, row=0, sticky="w")
        plot_frame = ttk.LabelFrame(plot_container, text="Voltage vs. sample")
        plot_frame.grid(column=0, row=1, sticky="nsew", pady=(8, 0))
        plot_container.rowconfigure(1, weight=1)

        self.figure, self.ax = plt.subplots(figsize=(5.5, 4))
        self.figure.subplots_adjust(left=0.12, right=0.95, bottom=0.15, top=0.92)
        self.ax.set_xlabel("Sample")
        self.ax.set_ylabel("Voltage (V)")
        self.ax.grid(True, linestyle="--", alpha=0.6)
        self.ax.set_title("Awaiting data")
        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # ------------------------------------------------------------- actions --
    def connect(self) -> None:
        address = self.address_var.get().strip()
        if not address:
            messagebox.showerror("Connect", "Please provide a VISA resource address.")
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
        self.inst = None
        self.rm = None
        self.script_loaded = False
        self.status_var.set("Disconnected")
        self._log("Disconnected.")
        self._update_buttons()

    def _load_script(self) -> None:
        if self.inst is None:
            return
        if not TSP_SOURCE.exists():
            messagebox.showerror("Script", f"Missing TSP file: {TSP_SOURCE}")
            return
        try:
            script_text = TSP_SOURCE.read_text(encoding="utf-8")
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
            self._log("TSP function loaded.")
        except pyvisa.VisaIOError as exc:
            messagebox.showerror("Script", f"Failed to load script: {exc}")
            self._log(f"Script load failed: {exc}")
            self.script_loaded = False

    def start_measurement(self) -> None:
        if not self._check_ready():
            return
        if self.running:
            messagebox.showinfo("Run", "Measurement already running.")
            return
        try:
            count_arg = self._format_number(self.measure_count_var.get(), allow_nil=True, integer=True)
            cur_arg = self._format_number(self.source_current_var.get(), allow_nil=True)
            src_range_arg = self._format_number(self.source_range_var.get(), allow_nil=True)
            meas_range_arg = self._format_number(self.measure_range_var.get(), allow_nil=True)
            nplc_arg = self._format_number(self.nplc_var.get(), allow_nil=True)
            trig_line = self._parse_line(self.trig_line_var.get())
        except ValueError as exc:
            messagebox.showerror("Parameters", str(exc))
            return
        edge = self.trig_edge_var.get().strip().lower()
        edge_arg = f"'{edge}'" if edge else "nil"

        command = (
            "run_fast_external_trigger("
            f"{count_arg}, {cur_arg}, {src_range_arg}, {meas_range_arg}, {trig_line}, {edge_arg}, {nplc_arg}"
            ")"
        )

        self.running = True
        self.cancel_requested = False
        self.latest_data = []
        self.status_var.set("Waiting for trigger...")
        self._log(
            "Waiting: count=%s, I=%s A, Irange=%s A, Vrange=%s V, NPLC=%s, line=%d (%s edge)"
            % (
                count_arg,
                cur_arg,
                src_range_arg,
                meas_range_arg,
                nplc_arg,
                trig_line,
                edge or "default",
            )
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
            self._log("Abort requested.")
        except pyvisa.VisaIOError as exc:
            self._log(f"Abort failed: {exc}")

    def _measurement_worker(self, command: str) -> None:
        inst = self.inst
        if inst is None:
            self._async_finish(error="Instrument disconnected.")
            return
        try:
            lines = self._execute_command(command)
        except pyvisa.VisaIOError as exc:
            self._async_finish(error=str(exc))
            return

        data, parse_error = self._parse_measurements(lines)
        if parse_error:
            self._async_finish(progress=lines, error=parse_error)
            return
        self._async_finish(progress=lines, data=data)

    def _async_finish(
        self,
        *,
        progress: list[str] | None = None,
        data: list[tuple[int, float]] | None = None,
        error: str | None = None,
    ) -> None:
        def finalize() -> None:
            self.running = False
            self.worker = None
            self._update_buttons()

            if progress:
                for line in progress:
                    self._log(line)

            if error:
                self.status_var.set("Measurement failed")
                messagebox.showerror("Run", error)
                return

            if not data:
                self.status_var.set("No data returned")
                self.result_var.set("No samples")
                self._update_plot([])
                return

            self.latest_data = data
            voltages = [v for _, v in data]
            self.status_var.set("Measurement complete")
            self.result_var.set(
                f"{len(voltages)} samples | min {min(voltages):.6g} V | max {max(voltages):.6g} V"
            )
            self._update_plot(data)

        self.root.after(0, finalize)

    # ------------------------------------------------------------- helpers --
    def _check_ready(self) -> bool:
        if self.inst is None:
            messagebox.showerror("Instrument", "Connect to the instrument first.")
            return False
        if not self.script_loaded:
            self._load_script()
        return self.script_loaded

    def _format_number(self, text: str, *, allow_nil: bool, integer: bool = False) -> str:
        stripped = text.strip()
        if not stripped:
            if allow_nil:
                return "nil"
            raise ValueError("Value cannot be empty.")
        try:
            value = float(stripped)
        except ValueError as exc:
            raise ValueError("Enter numeric values only.") from exc
        if integer:
            if value < 1:
                raise ValueError("Sample count must be >= 1.")
            return str(int(value))
        return f"{value:.9g}"

    def _parse_line(self, text: str) -> int:
        try:
            line = int(float(text.strip()))
        except ValueError as exc:
            raise ValueError("DIGIO line must be numeric.") from exc
        if not 1 <= line <= 6:
            raise ValueError("DIGIO line must be between 1 and 6.")
        return line

    def _execute_command(self, command: str) -> list[str]:
        if self.inst is None:
            raise RuntimeError("Instrument not connected.")
        inst = self.inst
        inst.write(command)
        original_timeout = inst.timeout
        lines: list[str] = []
        try:
            # First read waits for completion (can be long)
            chunk = inst.read().strip()
            if chunk:
                lines.append(chunk)
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
                if chunk:
                    lines.append(chunk)
        finally:
            inst.timeout = original_timeout
        return lines

    def _parse_measurements(self, lines: list[str]) -> tuple[list[tuple[int, float]], str | None]:
        data: list[tuple[int, float]] = []
        for line in lines:
            if not line:
                continue
            if line.lower().startswith("error"):
                return [], line
            if "reading" in line.lower() and "voltage" in line.lower():
                continue
            tokens = line.replace(",", " ").split()
            if len(tokens) < 2:
                continue
            try:
                idx = int(float(tokens[0]))
                val = float(tokens[1])
            except ValueError:
                continue
            data.append((idx, val))
        return data, None

    def _update_plot(self, data: list[tuple[int, float]]) -> None:
        if self.ax is None or self.canvas is None:
            return
        self.ax.clear()
        self.ax.set_xlabel("Sample")
        self.ax.set_ylabel("Voltage (V)")
        self.ax.grid(True, linestyle="--", alpha=0.6)
        if data:
            x_vals = [idx for idx, _ in data]
            y_vals = [val for _, val in data]
            self.ax.plot(x_vals, y_vals, marker="o", markersize=4, linewidth=1.4, color="tab:blue")
            self.ax.fill_between(x_vals, y_vals, color="tab:blue", alpha=0.2)
            self.ax.set_xlim(min(x_vals) - 0.5, max(x_vals) + 0.5)
            self.ax.set_title("Captured samples")
        else:
            self.ax.set_title("Awaiting data")
        self.canvas.draw_idle()

    def clear_log(self) -> None:
        if self.log_widget is None:
            return
        self.log_widget.configure(state=tk.NORMAL)
        self.log_widget.delete("1.0", tk.END)
        self.log_widget.configure(state=tk.DISABLED)

    def _log(self, message: str) -> None:
        if self.log_widget is None:
            return
        self.log_widget.configure(state=tk.NORMAL)
        self.log_widget.insert(tk.END, message + "\n")
        self.log_widget.see(tk.END)
        self.log_widget.configure(state=tk.DISABLED)

    def _update_buttons(self) -> None:
        connected = self.inst is not None
        self.btn_run.configure(state=tk.NORMAL if connected and not self.running else tk.DISABLED)
        self.btn_cancel.configure(state=tk.NORMAL if connected and self.running else tk.DISABLED)

    def on_close(self) -> None:
        try:
            self.disconnect()
        finally:
            if self.figure is not None:
                plt.close(self.figure)
            self.root.destroy()


def main() -> None:
    root = tk.Tk()
    ExternalTriggerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
