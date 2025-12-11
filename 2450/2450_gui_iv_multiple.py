import copy
import csv
import math
import sys
import threading
import tkinter as tk
from itertools import cycle
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import matplotlib.pyplot as plt
import pyvisa
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Default configuration
DEFAULT_ADDRESS = "TCPIP0::169.254.188.69::5025::SOCKET"
DEFAULT_START_V = "-4.0"
DEFAULT_STOP_V = "4.0"
DEFAULT_STEP_V = "0.1"
DEFAULT_ILIMIT = "0.5"
DEFAULT_NPLC = "1"
DEFAULT_SETTLE = "0.01"
DEFAULT_TOTAL_RUNS = "1"

RUN_COLORS = [
    "tab:blue",
    "tab:orange",
    "tab:green",
    "tab:red",
    "tab:purple",
    "tab:brown",
    "tab:pink",
    "tab:gray",
    "tab:olive",
    "tab:cyan",
]

TSP_PATH = Path(__file__).resolve().with_name("test_2450_iv_multiple.tsp")


class IVSweepApp:
    def __init__(self, root: tk.Misc, *, owns_root: bool = True) -> None:
        self.root = root
        self._owns_root = owns_root
        if isinstance(root, (tk.Tk, tk.Toplevel)):
            self._window = root
        else:
            self._window = root.winfo_toplevel()
        if self._owns_root:
            self._window.title("Keithley 2450 I-V Sweep")
        self.rm: pyvisa.ResourceManager | None = None
        self.inst = None
        self.script_loaded = False
        self.sweep_thread: threading.Thread | None = None
        self.current_data: list[tuple[float, float]] = []
        self.output_lines: list[str] = []
        self.stop_event = threading.Event()
        self.last_params: tuple[float, float, float, float, float, float] | None = None
        self.corrected_voltages: list[float] = []
        self.total_runs_var = tk.StringVar(value=DEFAULT_TOTAL_RUNS)
        self.run_results: list[dict] = []
        self.run_color_cycle = cycle(RUN_COLORS)
        self.wiring_var = tk.StringVar(value="4-wire")

        self._build_ui()
        if self._owns_root and hasattr(self._window, "protocol"):
            self._window.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self) -> None:
        main_frame = ttk.Frame(self.root, padding=12)
        main_frame.grid(column=0, row=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)

        self.address_var = tk.StringVar(value=DEFAULT_ADDRESS)
        self.start_var = tk.StringVar(value=DEFAULT_START_V)
        self.stop_var = tk.StringVar(value=DEFAULT_STOP_V)
        self.step_var = tk.StringVar(value=DEFAULT_STEP_V)
        self.ilimit_var = tk.StringVar(value=DEFAULT_ILIMIT)
        self.nplc_var = tk.StringVar(value=DEFAULT_NPLC)
        self.settle_var = tk.StringVar(value=DEFAULT_SETTLE)

        connection_frame = ttk.LabelFrame(main_frame, text="Instrument")
        connection_frame.grid(column=0, row=0, sticky="ew", pady=(0, 8))
        connection_frame.columnconfigure(1, weight=1)

        ttk.Label(connection_frame, text="VISA address:").grid(column=0, row=0, sticky="w")
        self.address_entry = ttk.Entry(connection_frame, textvariable=self.address_var, width=40)
        self.address_entry.grid(column=1, row=0, sticky="ew", padx=(4, 8))
        self.connect_button = ttk.Button(connection_frame, text="Connect", command=self.connect_instrument)
        self.connect_button.grid(column=2, row=0, padx=(0, 4))
        self.disconnect_button = ttk.Button(connection_frame, text="Disconnect", command=self.disconnect_instrument, state=tk.DISABLED)
        self.disconnect_button.grid(column=3, row=0)
        ttk.Label(connection_frame, text="Sense mode:").grid(column=0, row=1, sticky="w", pady=(6, 0))
        self.wiring_combo = ttk.Combobox(
            connection_frame,
            textvariable=self.wiring_var,
            values=("2-wire", "4-wire"),
            state="readonly",
            width=10,
        )
        self.wiring_combo.grid(column=1, row=1, sticky="w", padx=(4, 8), pady=(6, 0))
        connection_frame.grid_rowconfigure(1, weight=0)

        params_frame = ttk.LabelFrame(main_frame, text="Sweep Parameters")
        params_frame.grid(column=0, row=1, sticky="ew", pady=(0, 8))
        for col in range(0, 6, 2):
            params_frame.columnconfigure(col + 1, weight=1)

        self._add_labeled_entry(params_frame, 0, "Start voltage (V):", self.start_var)
        self._add_labeled_entry(params_frame, 1, "Stop voltage (V):", self.stop_var)
        self._add_labeled_entry(params_frame, 2, "Step voltage (V):", self.step_var)
        self._add_labeled_entry(params_frame, 3, "Compliance current (A):", self.ilimit_var)
        self._add_labeled_entry(params_frame, 4, "NPLC:", self.nplc_var)
        self._add_labeled_entry(params_frame, 5, "Settle time (s):", self.settle_var)

        controls_frame = ttk.Frame(main_frame)
        controls_frame.grid(column=0, row=2, sticky="ew")
        controls_frame.columnconfigure(0, weight=1)

        self.run_button = ttk.Button(controls_frame, text="Run Sweep", command=self.start_sweep, state=tk.DISABLED)
        self.run_button.grid(column=0, row=0, sticky="w")
        self.save_button = ttk.Button(controls_frame, text="Save CSV", command=self.save_csv, state=tk.DISABLED)
        self.save_button.grid(column=1, row=0, padx=(8, 0))
        ttk.Label(controls_frame, text="Total runs:").grid(column=2, row=0, sticky="e", padx=(16, 4))
        self.total_runs_entry = ttk.Entry(controls_frame, textvariable=self.total_runs_var, width=6)
        self.total_runs_entry.grid(column=3, row=0, sticky="w")

        plot_frame = ttk.LabelFrame(main_frame, text="I-V Curve")
        plot_frame.grid(column=0, row=3, sticky="nsew", pady=(8, 8))
        main_frame.rowconfigure(3, weight=1)
        plot_frame.columnconfigure(0, weight=1)
        plot_frame.rowconfigure(0, weight=1)

        self.figure, self.ax = plt.subplots(figsize=(6, 4))
        self.ax.set_xlabel("Voltage (V)")
        self.ax.set_ylabel("Current (A)")
        self.ax.grid(True)
        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        self.canvas.get_tk_widget().grid(column=0, row=0, sticky="nsew")

        log_frame = ttk.LabelFrame(main_frame, text="Output")
        log_frame.grid(column=0, row=4, sticky="nsew")
        main_frame.rowconfigure(4, weight=1)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, height=8, wrap="none", state=tk.DISABLED)
        self.log_text.grid(column=0, row=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(column=1, row=0, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _add_labeled_entry(self, parent: ttk.Frame, index: int, label: str, variable: tk.StringVar) -> None:
        ttk.Label(parent, text=label).grid(column=index * 2, row=0, sticky="w")
        entry = ttk.Entry(parent, textvariable=variable, width=12)
        entry.grid(column=index * 2 + 1, row=0, sticky="ew", padx=(4, 12))

    def connect_instrument(self) -> None:
        address = self.address_var.get().strip()
        if not address:
            messagebox.showerror("Instrument", "Please provide a VISA resource address.")
            return
        try:
            if self.rm is None:
                self.rm = pyvisa.ResourceManager()
            self.inst = self.rm.open_resource(address)
            self.inst.read_termination = "\n"
            self.inst.write_termination = "\n"
            self.inst.timeout = 100000
            idn = self.inst.query("*IDN?").strip()
            self.script_loaded = False
            self.log(f"Connected to {idn}")
            self.run_button.configure(state=tk.NORMAL)
            self.save_button.configure(state=tk.DISABLED)
            self.connect_button.configure(state=tk.DISABLED)
            self.disconnect_button.configure(state=tk.NORMAL)
        except pyvisa.VisaIOError as error:
            messagebox.showerror("Instrument", f"Connection failed: {error}")
            self.log(f"Connection failed: {error}")
            if self.inst is not None:
                self.inst.close()
            self.inst = None

    def disconnect_instrument(self) -> None:
        if self.inst is not None:
            try:
                self.inst.close()
            finally:
                self.inst = None
        if self.rm is not None:
            self.rm.close()
        self.rm = None
        self.script_loaded = False
        self.run_button.configure(state=tk.DISABLED)
        self.save_button.configure(state=tk.DISABLED)
        self.connect_button.configure(state=tk.NORMAL)
        self.disconnect_button.configure(state=tk.DISABLED)
        self.log("Disconnected.")
        self.last_params = None
        self.current_data.clear()
        self.corrected_voltages.clear()
        self.run_results.clear()
        self.output_lines.clear()
        self.run_color_cycle = cycle(RUN_COLORS)

    def ensure_script_loaded(self) -> None:
        if self.inst is None:
            raise RuntimeError("Instrument not connected.")
        if self.script_loaded:
            return
        if not TSP_PATH.exists():
            raise FileNotFoundError(f"Cannot locate TSP script at {TSP_PATH}")
        script_lines = TSP_PATH.read_text(encoding="utf-8").splitlines()
        try:
            self.inst.write("loadscript IVMultiple")
            for line in script_lines:
                self.inst.write(line)
            # Helper to expose the sweep with a stable entry point.
            self.inst.write("function IVMultiple_run(start_v, stop_v, step_v, ilimit, nplc, settle_s)")
            self.inst.write("    return iv_sweep_linear(start_v, stop_v, step_v, ilimit, nplc, settle_s)")
            self.inst.write("end")
            self.inst.write("endscript")
            self.inst.write("IVMultiple()")
            self.script_loaded = True
            self.log("iv_multiple.tsp loaded.")
        except pyvisa.VisaIOError as error:
            self.script_loaded = False
            raise RuntimeError(f"Failed to load TSP script: {error}") from error

    def start_sweep(self) -> None:
        if self.inst is None:
            messagebox.showerror("Instrument", "Connect to the instrument first.")
            return
        try:
            params = self._collect_parameters()
        except ValueError as error:
            messagebox.showerror("Parameters", str(error))
            return
        sweep_params = params[:6]
        total_runs = params[6]
        self.last_params = sweep_params
        self.corrected_voltages.clear()
        self.current_data.clear()
        self.run_results.clear()
        self.run_color_cycle = cycle(RUN_COLORS)
        self.output_lines.clear()
        self.run_button.configure(state=tk.DISABLED)
        self.save_button.configure(state=tk.DISABLED)
        self.log("Starting sweep...")
        if self.sweep_thread and self.sweep_thread.is_alive():
            self.stop_event.set()
            self.sweep_thread.join(timeout=1.0)
        self.stop_event.clear()
        self.sweep_thread = threading.Thread(
            target=self._sweep_worker, args=(sweep_params, total_runs), daemon=True
        )
        self.sweep_thread.start()

    def _collect_parameters(self) -> tuple[float, float, float, float, float, float, int]:
        def parse_float(value: str, label: str) -> float:
            try:
                return float(value)
            except ValueError as error:
                raise ValueError(f"{label} must be a number.") from error

        start_v = parse_float(self.start_var.get(), "Start voltage")
        stop_v = parse_float(self.stop_var.get(), "Stop voltage")
        step_v = parse_float(self.step_var.get(), "Step voltage")
        if step_v == 0.0:
            raise ValueError("Step voltage must not be zero.")
        ilimit = abs(parse_float(self.ilimit_var.get(), "Compliance current"))
        nplc = max(parse_float(self.nplc_var.get(), "NPLC"), 0.001)
        settle = max(parse_float(self.settle_var.get(), "Settle time"), 0.0)
        total_runs_value = self.total_runs_var.get().strip()
        if not total_runs_value:
            raise ValueError("Total runs must be provided.")
        try:
            total_runs_float = float(total_runs_value)
        except ValueError as error:
            raise ValueError("Total runs must be an integer.") from error
        if not total_runs_float.is_integer():
            raise ValueError("Total runs must be an integer.")
        total_runs = int(total_runs_float)
        if total_runs < 1:
            raise ValueError("Total runs must be at least 1.")
        return start_v, stop_v, step_v, ilimit, nplc, settle, total_runs

    def _sweep_worker(
        self, params: tuple[float, float, float, float, float, float], total_runs: int
    ) -> None:
        segments, command_levels = self._build_segments(params)
        run_entries: list[dict] = []
        tolerance = max(abs(params[2]) * 0.02, 1e-6)
        try:
            self.ensure_script_loaded()
            if self.stop_event.is_set():
                return
            self._apply_wiring_mode()
            if self.stop_event.is_set():
                return
            for run_index in range(total_runs):
                if self.stop_event.is_set():
                    raise RuntimeError("Sweep cancelled.")
                command_index = [0]
                run_voltages: list[float] = []
                run_currents: list[float] = []
                run_lines: list[str] = []
                run_commanded: list[float] = []
                color = next(self.run_color_cycle)
                current_entry = {
                    "run_index": run_index + 1,
                    "actual_voltages": [],
                    "currents": [],
                    "corrected_voltages": [],
                    "printed_lines": [],
                    "point_count": 0,
                    "color": color,
                    "adjusted": False,
                }
                run_entries.append(current_entry)
                for segment_index, (seg_start, seg_stop, seg_step) in enumerate(segments):
                    if self.stop_event.is_set():
                        raise RuntimeError("Sweep cancelled.")
                    segment_start_idx = command_index[0]
                    def handle_point(voltage: float, current: float) -> None:
                        commanded = (
                            command_levels[command_index[0]]
                            if command_index[0] < len(command_levels)
                            else voltage
                        )
                        command_index[0] += 1
                        run_voltages.append(voltage)
                        run_currents.append(current)
                        run_commanded.append(commanded)
                        if abs(voltage - commanded) > tolerance:
                            current_entry["adjusted"] = True
                        current_entry["actual_voltages"] = list(run_voltages)
                        current_entry["currents"] = list(run_currents)
                        current_entry["corrected_voltages"] = list(run_commanded)
                        current_entry["point_count"] = len(run_currents)
                        snapshot = self._snapshot_entries(run_entries)
                        self.root.after(
                            0,
                            lambda snap=snapshot: self._update_live_plot(snap),
                        )
                    segment_voltages, segment_currents, segment_lines = self._perform_sweep(
                        params,
                        run_index,
                        segment_index,
                        seg_start,
                        seg_stop,
                        seg_step,
                        run_lines,
                        handle_point,
                    )
                    run_lines.append(
                        f"# Run {run_index + 1} segment {segment_index + 1}: {seg_start} -> {seg_stop}"
                    )
                    run_lines.extend(segment_lines)
                    segment_end_idx = command_index[0]
                    command_slice = command_levels[segment_start_idx:segment_end_idx]
                    if segment_voltages:
                        segment_corrected = self._match_voltage_sequence(
                            command_slice, segment_voltages
                        )
                        if segment_corrected:
                            run_commanded[segment_start_idx:segment_end_idx] = segment_corrected
                            if any(
                                abs(measured - commanded) > tolerance
                                for measured, commanded in zip(
                                    segment_voltages, segment_corrected
                                )
                            ):
                                current_entry["adjusted"] = True
                    if segment_voltages:
                        seg_len = len(segment_voltages)
                        run_voltages[-seg_len:] = segment_voltages
                        run_currents[-seg_len:] = segment_currents
                    current_entry["actual_voltages"] = list(run_voltages)
                    current_entry["currents"] = list(run_currents)
                    current_entry["corrected_voltages"] = list(run_commanded)
                    current_entry["printed_lines"] = list(run_lines)
                    current_entry["point_count"] = len(run_currents)
                    snapshot = self._snapshot_entries(run_entries)
                    self.root.after(
                        0, lambda snap=snapshot: self._update_live_plot(snap)
                    )
        except Exception as error:
            self.root.after(0, lambda err=error: self._on_sweep_failed(err))
            return
        self.root.after(0, lambda entries=run_entries: self._on_sweep_complete(entries))

    def _perform_sweep(
        self,
        params: tuple[float, float, float, float, float, float],
        run_index: int,
        segment_index: int,
        seg_start: float,
        seg_stop: float,
        seg_step: float,
        run_lines: list[str],
        on_point,
    ) -> tuple[list[float], list[float], list[str]]:
        if self.inst is None:
            raise RuntimeError("Instrument not connected.")
        _, _, _, ilimit, nplc, settle = params
        command = f"IVMultiple_run({seg_start}, {seg_stop}, {seg_step}, {ilimit}, {nplc}, {settle})"
        self.inst.write(command)
        marker = f"SWEEP_DONE_{run_index + 1}_{segment_index + 1}"
        self.inst.write(f"print('{marker}')")
        segment_voltages: list[float] = []
        segment_currents: list[float] = []

        def handle_line(line: str) -> None:
            parsed = self._parse_measurement_line(line)
            if parsed is None:
                return
            voltage, current = parsed
            segment_voltages.append(voltage)
            segment_currents.append(current)
            on_point(voltage, current)

        printed_lines = self._read_until_marker(marker, handle_line)
        run_lines.extend(printed_lines)
        point_count = int(float(self.inst.query("print(defbuffer1.n)").strip()))
        voltages = self._fetch_buffer("defbuffer1.sourcevalues", point_count)
        currents = self._fetch_buffer("defbuffer1", point_count)
        if len(voltages) != point_count or len(currents) != point_count:
            parsed = self._parse_printed_lines(printed_lines)
            if parsed:
                volts, amps = zip(*parsed)
                voltages = list(volts)
                currents = list(amps)
        voltages = list(voltages)
        currents = list(currents)
        count = min(len(voltages), len(currents))
        voltages = voltages[:count]
        currents = currents[:count]
        segment_voltages = voltages
        segment_currents = currents
        return segment_voltages, segment_currents, printed_lines

    def _read_until_marker(self, marker: str, on_line=None) -> list[str]:
        if self.inst is None:
            return []
        lines: list[str] = []
        while True:
            try:
                if self.stop_event.is_set():
                    raise RuntimeError("Sweep cancelled.")
                line = self.inst.read().strip()
            except pyvisa.VisaIOError as error:
                raise RuntimeError(f"Failed while waiting for sweep output: {error}") from error
            if line == marker:
                break
            if line:
                if on_line is not None:
                    try:
                        on_line(line)
                    except Exception:
                        pass
                lines.append(line)
        return lines

    def _apply_wiring_mode(self) -> None:
        if self.inst is None:
            return
        mode = self.wiring_var.get().lower()
        try:
            commands = [
                "pcall(function() smu.measure.terminals = smu.TERMINALS_FRONT end)",
                "pcall(function() smu.source.terminals = smu.TERMINALS_FRONT end)",
            ]
            if mode.startswith("4"):
                commands.append(
                    "pcall(function() smu.measure.sense = smu.SENSE_4WIRE end)"
                )
            else:
                commands.append(
                    "pcall(function() smu.measure.sense = smu.SENSE_2WIRE end)"
                )
            for command in commands:
                self.inst.write(command)
        except pyvisa.VisaIOError as error:
            raise RuntimeError(f"Failed to set {self.wiring_var.get()} mode: {error}") from error

    def _build_segments(
        self, params: tuple[float, float, float, float, float, float]
    ) -> tuple[list[tuple[float, float, float]], list[float]]:
        start_v, stop_v, step_v, *_ = params
        step_mag = abs(step_v)
        if math.isclose(step_mag, 0.0, abs_tol=1e-15):
            raise ValueError("Step voltage must not be zero.")
        epsilon = step_mag * 1e-9 + 1e-12
        segments: list[tuple[float, float, float]] = []
        path_levels: list[float] = []

        def generate_segment_levels(start: float, stop: float, seg_step: float) -> list[float]:
            levels = [start]
            if math.isclose(seg_step, 0.0, abs_tol=epsilon):
                return levels
            direction = 1 if seg_step > 0 else -1
            current = start
            while True:
                next_level = current + seg_step
                if direction > 0 and next_level > stop + epsilon:
                    next_level = stop
                elif direction < 0 and next_level < stop - epsilon:
                    next_level = stop
                if math.isclose(next_level, current, abs_tol=epsilon):
                    break
                levels.append(next_level)
                current = next_level
                if math.isclose(current, stop, abs_tol=epsilon):
                    break
            return levels

        def append_segment(start: float, stop: float) -> None:
            if math.isclose(start, stop, abs_tol=epsilon):
                return
            seg_step = step_mag if stop >= start else -step_mag
            segments.append((start, stop, seg_step))
            segment_levels = generate_segment_levels(start, stop, seg_step)
            path_levels.extend(segment_levels)

        positive_target = max(start_v, stop_v, 0.0)
        negative_target = min(start_v, stop_v, 0.0)

        if positive_target > epsilon:
            append_segment(0.0, positive_target)
            append_segment(positive_target, 0.0)
        if negative_target < -epsilon:
            append_segment(0.0, negative_target)
            append_segment(negative_target, 0.0)

        if not segments:
            segments.append((start_v, stop_v, step_v))
            path_levels = generate_segment_levels(start_v, stop_v, step_v)

        if not path_levels:
            path_levels.append(0.0)

        return segments, path_levels

    def _match_voltage_sequence(self, expected: list[float], actual: list[float]) -> list[float]:
        if not expected or not actual:
            return actual
        length = min(len(expected), len(actual))
        step_candidates = [
            abs(expected[i + 1] - expected[i])
            for i in range(length - 1)
            if not math.isclose(expected[i + 1], expected[i], abs_tol=1e-12)
        ]
        base_step = min(step_candidates) if step_candidates else 0.0
        tolerance = max(base_step * 0.02, 1e-6)
        matched: list[float] = []
        stuck_index: int | None = None
        for idx in range(length):
            exp_value = expected[idx]
            act_value = actual[idx]
            if stuck_index is None and abs(exp_value - act_value) > tolerance:
                stuck_index = idx
            if stuck_index is None:
                matched.append(act_value)
            else:
                matched.append(exp_value)
        if len(actual) > length:
            matched.extend(actual[length:])
        return matched

    def _render_plot(self, runs: list[dict]) -> None:
        self.ax.clear()
        self.ax.set_xlabel("Voltage (V)")
        self.ax.set_ylabel("Current (A)")
        self.ax.grid(True)
        for entry in runs:
            voltages = entry["corrected_voltages"] or entry["actual_voltages"]
            currents = entry["currents"]
            if not voltages or not currents:
                continue
            label = f"Run {entry['run_index']}"
            self.ax.plot(
                voltages,
                currents,
                marker="o",
                linestyle="-",
                color=entry.get("color"),
                label=label,
            )
        if len([run for run in runs if run["currents"]]) > 1:
            self.ax.legend()
        self.canvas.draw_idle()

    def _snapshot_entries(self, entries: list[dict]) -> list[dict]:
        return copy.deepcopy(entries)

    def _update_live_plot(self, entries: list[dict]) -> None:
        self.run_results = entries
        if entries:
            last = entries[-1]
            corrected = list(last.get("corrected_voltages", []))
            currents = list(last.get("currents", []))
            self.corrected_voltages = corrected
            self.current_data = list(zip(corrected, currents))
        else:
            self.corrected_voltages = []
            self.current_data = []
        self._render_plot(entries)

    def _parse_printed_lines(self, lines: list[str]) -> list[tuple[float, float]]:
        data: list[tuple[float, float]] = []
        for line in lines:
            sanitized = line.replace(",", " ").strip()
            parts = sanitized.split()
            if len(parts) < 3:
                continue
            try:
                # First column is point index; ignore.
                float(parts[0])
                voltage = float(parts[1])
                current = float(parts[2])
            except ValueError:
                continue
            data.append((voltage, current))
        return data

    def _parse_measurement_line(self, line: str) -> tuple[float, float] | None:
        sanitized = line.replace(",", " ").strip()
        parts = sanitized.split()
        if len(parts) < 3:
            return None
        try:
            float(parts[0])
            voltage = float(parts[1])
            current = float(parts[2])
        except ValueError:
            return None
        return voltage, current

    def _fetch_buffer(self, accessor: str, count: int) -> list[float]:
        if self.inst is None or count == 0:
            return []
        try:
            response = self.inst.query(f"printbuffer(1, {count}, {accessor})").strip()
        except pyvisa.VisaIOError as error:
            raise RuntimeError(f"Failed to fetch buffer data for {accessor}: {error}") from error
        if not response:
            return []
        values = []
        for token in response.replace("\n", ",").split(","):
            token = token.strip()
            if not token:
                continue
            try:
                values.append(float(token))
            except ValueError:
                pass
        return values

    def _on_sweep_complete(self, entries: list[dict]) -> None:
        self._update_live_plot(entries)
        self.run_button.configure(state=tk.NORMAL)
        if entries:
            self.output_lines = entries[-1].get("printed_lines", [])
            self.save_button.configure(state=tk.NORMAL)
            self.log(f"Sense mode: {self.wiring_var.get()}")
            for entry in entries:
                self.log(
                    f"Run {entry['run_index']}: Received {entry['point_count']} points."
                )
                if entry.get("adjusted"):
                    self.log(
                        f"Run {entry['run_index']}: Applied commanded voltage levels after current limit."
                )
                for line in entry.get("printed_lines", []):
                    self.log(line)
            self.log("Sweep finished.")
        else:
            self.run_results.clear()
            self.current_data.clear()
            self.corrected_voltages.clear()
            self.save_button.configure(state=tk.DISABLED)
            self.log("Sweep finished but no data was returned.")

    def _on_sweep_failed(self, error: Exception) -> None:
        messagebox.showerror("Sweep", str(error))
        self.log(f"Sweep failed: {error}")
        self.run_button.configure(state=tk.NORMAL)
        self.save_button.configure(state=tk.DISABLED)
        self.run_results.clear()
        self.current_data.clear()
        self.corrected_voltages.clear()
        self.output_lines.clear()

    def save_csv(self) -> None:
        if not self.run_results:
            messagebox.showinfo("Save CSV", "No data to save.")
            return
        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="Save I-V data",
        )
        if not filename:
            return
        try:
            with open(filename, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(
                    ["Run", "Commanded Voltage (V)", "Measured Voltage (V)", "Current (A)"]
                )
                for entry in self.run_results:
                    commanded = entry["corrected_voltages"] or entry["actual_voltages"]
                    measured = entry["actual_voltages"]
                    currents = entry["currents"]
                    count = min(len(commanded), len(measured), len(currents))
                    for idx in range(count):
                        writer.writerow(
                            [
                                entry["run_index"],
                                commanded[idx],
                                measured[idx],
                                currents[idx],
                            ]
                        )
            self.log(f"Saved data to {filename}")
        except OSError as error:
            messagebox.showerror("Save CSV", f"Failed to save file: {error}")

    def log(self, message: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def on_close(self) -> None:
        self.stop_event.set()
        if self.sweep_thread and self.sweep_thread.is_alive():
            self.sweep_thread.join(timeout=2.0)
        try:
            self.disconnect_instrument()
        except Exception:
            pass
        plt.close(self.figure)
        if self._owns_root:
            self.root.quit()
            self.root.destroy()
            sys.exit(0)


def main() -> None:
    root = tk.Tk()
    app = IVSweepApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
