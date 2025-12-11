"""Tkinter GUI for configuring and running 2450 trigger-based voltage measurements."""

from __future__ import annotations

import pathlib
import sys
import tkinter as tk
from tkinter import messagebox, ttk

import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import pyvisa

DEFAULT_ADDRESS = "TCPIP0::169.254.188.69::5025::SOCKET"
SCRIPT_NAME = "TriggerVoltmeter"
SCRIPT_PATH = pathlib.Path(__file__).with_name("2450_async_trigger_measure_voltage.tsp")
DRAIN_TIMEOUT_MS = 250


class TriggerMeasureGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("2450 Triggered Voltmeter")
        self.root.minsize(960, 640)

        self.rm: pyvisa.ResourceManager | None = None
        self.inst = None
        self.script_loaded = False

        self.address_var = tk.StringVar(value=DEFAULT_ADDRESS)
        self.range_var = tk.StringVar(value="2")
        self.nplc_var = tk.StringVar(value="0.01")
        self.manual_count_var = tk.StringVar(value="5")
        self.manual_timeout_var = tk.StringVar(value="20")
        self.auto_count_var = tk.StringVar(value="25")
        self.auto_interval_var = tk.StringVar(value="0.05")

        self.figure = None
        self.ax = None
        self.canvas = None

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------------ UI --
    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.grid(column=0, row=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)

        # Connection controls
        ttk.Label(frame, text="VISA address:").grid(column=0, row=0, sticky="w")
        ttk.Entry(frame, textvariable=self.address_var, width=45).grid(
            column=1, row=0, columnspan=2, sticky="ew", padx=(4, 8)
        )
        ttk.Button(frame, text="Connect", command=self.connect).grid(column=3, row=0)
        ttk.Button(frame, text="Disconnect", command=self.disconnect).grid(
            column=4, row=0, padx=(6, 0)
        )

        # Configuration parameters
        config_box = ttk.LabelFrame(frame, text="Configuration")
        config_box.grid(column=0, row=1, columnspan=5, sticky="ew", pady=(12, 0))
        config_box.columnconfigure(5, weight=1)

        ttk.Label(config_box, text="Range (V):").grid(column=0, row=0, sticky="w")
        ttk.Entry(config_box, textvariable=self.range_var, width=10).grid(
            column=1, row=0, sticky="w", padx=(4, 16)
        )
        ttk.Label(config_box, text="NPLC:").grid(column=2, row=0, sticky="w")
        ttk.Entry(config_box, textvariable=self.nplc_var, width=10).grid(
            column=3, row=0, sticky="w", padx=(4, 16)
        )
        ttk.Button(config_box, text="Configure", command=self.configure_meter).grid(
            column=4, row=0, padx=(4, 0)
        )
        ttk.Button(config_box, text="Output Off", command=self.output_off).grid(
            column=5, row=0, padx=(8, 0), sticky="e"
        )

        # Manual trigger section
        manual_box = ttk.LabelFrame(frame, text="Manual trigger (front panel)")
        manual_box.grid(column=0, row=2, columnspan=5, sticky="ew", pady=(12, 0))
        ttk.Label(manual_box, text="Trigger count:").grid(column=0, row=0, sticky="w")
        ttk.Entry(manual_box, textvariable=self.manual_count_var, width=8).grid(
            column=1, row=0, sticky="w", padx=(4, 16)
        )
        ttk.Label(manual_box, text="Timeout per trigger (s):").grid(
            column=2, row=0, sticky="w"
        )
        ttk.Entry(manual_box, textvariable=self.manual_timeout_var, width=10).grid(
            column=3, row=0, sticky="w", padx=(4, 16)
        )
        ttk.Button(
            manual_box,
            text="Run Manual Sequence",
            command=self.run_manual_trigger,
        ).grid(column=4, row=0, padx=(4, 0))

        # Automatic trigger section
        auto_box = ttk.LabelFrame(frame, text="Automatic trigger")
        auto_box.grid(column=0, row=3, columnspan=5, sticky="ew", pady=(12, 0))
        ttk.Label(auto_box, text="Samples:").grid(column=0, row=0, sticky="w")
        ttk.Entry(auto_box, textvariable=self.auto_count_var, width=8).grid(
            column=1, row=0, sticky="w", padx=(4, 16)
        )
        ttk.Label(auto_box, text="Interval (s, 0 = fastest):").grid(
            column=2, row=0, sticky="w"
        )
        ttk.Entry(auto_box, textvariable=self.auto_interval_var, width=10).grid(
            column=3, row=0, sticky="w", padx=(4, 16)
        )
        ttk.Button(
            auto_box,
            text="Run Auto Sequence",
            command=self.run_auto_trigger,
        ).grid(column=4, row=0, padx=(4, 0))

        # Output log
        self.log_box = tk.Text(frame, height=12, width=80, state=tk.DISABLED)
        self.log_box.grid(column=0, row=4, columnspan=5, sticky="nsew", pady=(12, 0))
        frame.rowconfigure(4, weight=1)

        # Plot
        plot_frame = ttk.LabelFrame(self.root, text="Captured Voltages")
        plot_frame.grid(column=0, row=1, sticky="nsew", padx=12, pady=(0, 12))
        self.root.rowconfigure(1, weight=2)
        plot_frame.columnconfigure(0, weight=1)
        plot_frame.rowconfigure(0, weight=1)

        self.figure, self.ax = plt.subplots(figsize=(8, 4))
        self.figure.subplots_adjust(left=0.09, right=0.98, bottom=0.16, top=0.92)
        self.ax.set_xlabel("Sample")
        self.ax.set_ylabel("Voltage (V)")
        self.ax.grid(True, linestyle="--", alpha=0.6)
        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        self.canvas.get_tk_widget().configure(highlightthickness=0)
        self.canvas.get_tk_widget().grid(column=0, row=0, sticky="nsew")

    # ------------------------------------------------------------ connection --
    def connect(self) -> None:
        address = self.address_var.get().strip()
        if not address:
            messagebox.showerror("Connect", "Please provide a VISA address.")
            return
        try:
            if self.rm is None:
                self.rm = pyvisa.ResourceManager()
            self.inst = self.rm.open_resource(address)
            self.inst.read_termination = "\n"
            self.inst.write_termination = "\n"
            self.inst.timeout = 20000
            idn = self.inst.query("*IDN?").strip()
            self._log(f"Connected to {idn}")
            self._load_script()
        except pyvisa.VisaIOError as exc:
            messagebox.showerror("Connect", f"Connection failed: {exc}")
            self._log(f"Connection failed: {exc}")
            self.inst = None

    def disconnect(self) -> None:
        if self.inst is not None:
            try:
                self.inst.write("smu.source.output = smu.OFF")
            except pyvisa.VisaIOError:
                pass
            self.inst.close()
        if self.rm is not None:
            self.rm.close()
        self.rm = None
        self.inst = None
        self.script_loaded = False
        self._log("Disconnected.")

    # ---------------------------------------------------------------- script --
    def _load_script(self) -> None:
        if self.inst is None or self.script_loaded:
            return
        if not SCRIPT_PATH.exists():
            messagebox.showerror("Script", f"TSP file not found: {SCRIPT_PATH}")
            return
        script_text = SCRIPT_PATH.read_text(encoding="utf-8")

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

    # ------------------------------------------------------------ operations --
    def configure_meter(self) -> None:
        if not self._ensure_ready():
            return
        try:
            range_arg = self._format_float(self.range_var.get(), default="2")
            nplc_arg = self._format_float(self.nplc_var.get(), default="0.01")
        except ValueError as exc:
            messagebox.showerror("Configure", str(exc))
            return
        try:
            self.inst.write(f"configure_voltmeter({range_arg}, {nplc_arg})")
            self._log(
                f"Configured: range={range_arg} V, NPLC={nplc_arg}. Output enabled."
            )
        except pyvisa.VisaIOError as exc:
            messagebox.showerror("Configure", f"Failed to configure: {exc}")
            self._log(f"Configure failed: {exc}")

    def run_manual_trigger(self) -> None:
        if not self._ensure_ready():
            return
        try:
            count = int(float(self.manual_count_var.get()))
            timeout = self._format_float(self.manual_timeout_var.get(), default="30")
        except ValueError:
            messagebox.showerror(
                "Manual Sequence", "Count and timeout must be numeric values."
            )
            return
        try:
            lines = self._query_lines(
                f"print(triggered_voltage_measurements({count}, {timeout}))"
            )
        except pyvisa.VisaIOError as exc:
            messagebox.showerror("Manual Sequence", f"Failed: {exc}")
            self._log(f"Manual trigger failed: {exc}")
            return
        count_line, progress_lines = self._split_numeric_tail(lines)
        for line in progress_lines:
            self._log(line)
        captured = self._parse_count(count_line)
        count_display = str(captured) if captured is not None else (count_line or "unknown")
        self._log(
            f"Manual trigger complete. Captured {count_display} reading(s). Pressed TRIG {count_display} time(s)."
        )
        self._fetch_and_plot_buffer()

    def run_auto_trigger(self) -> None:
        if not self._ensure_ready():
            return
        try:
            count = int(float(self.auto_count_var.get()))
            interval = self._format_float(self.auto_interval_var.get(), default="0")
        except ValueError:
            messagebox.showerror(
                "Auto Sequence", "Count and interval must be numeric values."
            )
            return
        try:
            lines = self._query_lines(
                f"print(auto_triggered_voltage_measurements({count}, {interval}))"
            )
        except pyvisa.VisaIOError as exc:
            messagebox.showerror("Auto Sequence", f"Failed: {exc}")
            self._log(f"Auto trigger failed: {exc}")
            return
        count_line, progress_lines = self._split_numeric_tail(lines)
        for line in progress_lines:
            self._log(line)
        captured = self._parse_count(count_line)
        count_display = str(captured) if captured is not None else (count_line or "unknown")
        self._log(
            f"Auto trigger complete. Captured {count_display} reading(s) with interval={interval} s."
        )
        self._fetch_and_plot_buffer()

    def output_off(self) -> None:
        if self.inst is None:
            return
        try:
            self.inst.write("smu.source.output = smu.OFF")
            self._log("Source output disabled.")
        except pyvisa.VisaIOError as exc:
            self._log(f"Failed to turn output off: {exc}")

    # -------------------------------------------------------------- helpers --
    def _ensure_ready(self) -> bool:
        if self.inst is None:
            messagebox.showwarning("Instrument", "Connect to the instrument first.")
            return False
        if not self.script_loaded:
            self._load_script()
        return self.script_loaded

    def _format_float(self, value: str, *, default: str = "nil") -> str:
        text = value.strip()
        if not text:
            return default
        float(text)  # raises ValueError if invalid
        return text

    def _fetch_and_plot_buffer(self) -> None:
        if self.inst is None:
            return
        try:
            lines = self._query_lines("printbuffer(1, defbuffer1.n, defbuffer1)")
        except pyvisa.VisaIOError as exc:
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
        if self.inst is None:
            return []
        self.inst.write(command)
        return self._read_response_lines()

    def _read_response_lines(self) -> list[str]:
        assert self.inst is not None
        lines: list[str] = []
        original_timeout = self.inst.timeout
        try:
            first_line = self.inst.read().strip()
            if first_line:
                lines.append(first_line)
        except pyvisa.VisaIOError:
            self.inst.timeout = original_timeout
            raise
        try:
            drain_timeout = min(original_timeout, DRAIN_TIMEOUT_MS)
            self.inst.timeout = drain_timeout
            while True:
                try:
                    extra = self.inst.read().strip()
                except pyvisa.VisaIOError as exc:
                    if exc.error_code == pyvisa.constants.VI_ERROR_TMO:
                        break
                    raise
                if extra:
                    lines.append(extra)
        finally:
            self.inst.timeout = original_timeout
        return lines

    def _split_numeric_tail(self, lines: list[str]) -> tuple[str | None, list[str]]:
        if not lines:
            return None, []
        for idx in range(len(lines) - 1, -1, -1):
            if self._is_float(lines[idx]):
                numeric_line = lines[idx]
                remainder = lines[:idx] + lines[idx + 1 :]
                return numeric_line, remainder
        return None, list(lines)

    def _parse_count(self, line: str | None) -> int | None:
        if line is None:
            return None
        try:
            value = float(line)
        except ValueError:
            return None
        return int(round(value))

    def _is_float(self, text: str) -> bool:
        try:
            float(text)
            return True
        except ValueError:
            return False

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

    def _update_plot(self, voltages: list[float]) -> None:
        self.ax.clear()
        self.ax.set_xlabel("Sample")
        self.ax.set_ylabel("Voltage (V)")
        self.ax.grid(True, linestyle="--", alpha=0.6)
        if voltages:
            x_vals = list(range(1, len(voltages) + 1))
            self.ax.plot(
                x_vals,
                voltages,
                marker="o",
                markersize=4,
                linewidth=1.5,
                color="tab:blue",
            )
            self.ax.fill_between(x_vals, voltages, color="tab:blue", alpha=0.12)
            self.ax.set_xlim(0.5, len(voltages) + 0.5)
        self.ax.set_title("Latest capture")
        self.canvas.draw_idle()

    def _log(self, message: str) -> None:
        self.log_box.configure(state=tk.NORMAL)
        self.log_box.insert(tk.END, message + "\n")
        self.log_box.see(tk.END)
        self.log_box.configure(state=tk.DISABLED)

    def on_close(self) -> None:
        try:
            if self.figure:
                plt.close(self.figure)
        except Exception:
            pass
        self.disconnect()
        self.root.quit()
        self.root.destroy()
        sys.exit(0)


def main() -> None:
    root = tk.Tk()
    TriggerMeasureGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
