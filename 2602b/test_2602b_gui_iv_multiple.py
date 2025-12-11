import tkinter as tk
from tkinter import messagebox
import pyvisa
import csv  # Import the CSV module
import time
import math
from itertools import cycle
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

# VISA resource configuration
ADDRESS = "TCPIP0::169.254.0.1::5025::SOCKET"  # Change this to your instrument's address
rm = pyvisa.ResourceManager()
inst = None
measurements = []  # Global variable to store measurements
measurement_values = []  # Numeric current readings (amps)
run_traces = []  # Holds per-run trace metadata for plotting
MEASUREMENT_DELAY_SECONDS = 0.05  # Delay between trigger measurements for smoother plotting
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
run_color_cycle = cycle(RUN_COLORS)


def compute_poll_interval_ms():
    """Return GUI poll interval derived from measurement delay."""
    base_delay = max(MEASUREMENT_DELAY_SECONDS, 0.01)
    return max(100, int(base_delay * 1000 * 1.5))
sweep_state = {
    "configured": False,
    "running": False,
    "single_run_voltages": [],
    "points_per_run": 0,
    "start_voltage": 0.0,
    "stop_voltage": 0.0,
    "current_index": 0,
    "total_points": 0,
    "compliance": None,
    "total_runs": 0,
    "inputs_snapshot": None,
    "elapsed_time": 0.0,
    "segment_start": None,
    "monitor_job": None,
    "pending_points": 0,
    "segment_points": 0,
    "segment_start_index": 0,
    "timer_started": False,
}

# Helper function to format values in SI units
def format_si_units(value, unit="A"):
    value = float(value)  # Ensure the value is a float
    prefixes = [
        (1e-6, "µ"),
        (1e-3, "m"),
        (1, ""),  # Base unit
        (1e3, "k"),
        (1e6, "M"),
    ]
    for factor, prefix in prefixes:
        if abs(value) < factor * 1000:  # Stay within 3 significant digits
            return f"{value / factor:.3f} {prefix}{unit}"
    return f"{value:.3e} {unit}"  # Fallback to scientific notation


def parse_total_runs():
    """Return the user-configured number of consecutive sweeps."""
    runs_value = entry_total_runs.get().strip()
    if not runs_value:
        raise ValueError("Total runs must be provided.")
    runs_float = float(runs_value)
    if not runs_float.is_integer():
        raise ValueError("Total runs must be an integer.")
    runs = int(runs_float)
    if runs < 1:
        raise ValueError("Total runs must be at least 1.")
    return runs


def compute_single_run_voltages():
    """Generate the voltage sequence: 0→positive target, then negative target→0."""
    positive_input = float(entry_start_voltage.get())
    negative_input = float(entry_stop_voltage.get())
    step_mag = abs(float(entry_step_voltage.get()))
    if math.isclose(step_mag, 0.0, abs_tol=1e-12):
        raise ValueError("Step voltage must not be zero.")

    positive_target = abs(positive_input)
    negative_target = -abs(negative_input)
    tol = step_mag * 1e-9 + 1e-12

    sequence = []

    def append_unique(value):
        if not sequence or not math.isclose(sequence[-1], value, rel_tol=1e-9, abs_tol=tol):
            sequence.append(value)

    append_unique(0.0)

    # 0 -> +target
    if positive_target > tol:
        current = 0.0
        while current + step_mag < positive_target - tol:
            current += step_mag
            append_unique(current)
        append_unique(positive_target)
        # Return to 0
        current = sequence[-1]
        while current - step_mag > tol:
            current -= step_mag
            append_unique(current)
        append_unique(0.0)

    # 0 -> negative target -> 0
    if negative_target < -tol:
        current = 0.0
        while current - step_mag > negative_target + tol:
            current -= step_mag
            append_unique(current)
        append_unique(negative_target)
        current = negative_target
        while current + step_mag < -tol:
            current += step_mag
            append_unique(current)
        append_unique(0.0)

    return sequence


def build_voltage_sequence(length):
    """Return voltage list repeated to cover `length` measurements."""
    single_run = compute_single_run_voltages()
    parse_total_runs()  # validate input even if not directly used here
    sequence = []
    if not single_run:
        return sequence
    repeats_needed = max(math.ceil(length / len(single_run)), 1)
    for _ in range(repeats_needed):
        sequence.extend(single_run)
        if len(sequence) >= length:
            break
    return sequence[:length]

def clear_measurement_records():
    """Reset all cached measurement data and clear UI widgets."""
    measurements.clear()
    measurement_values.clear()
    run_traces.clear()
    global run_color_cycle
    run_color_cycle = cycle(RUN_COLORS)
    if "text_measurements" in globals():
        try:
            text_measurements.config(state="normal")
            text_measurements.delete(1.0, tk.END)
            text_measurements.config(state="disabled")
        except Exception:
            pass


def append_measurement_display(index, formatted_value):
    """Append a single measurement line to the text widget."""
    if "text_measurements" not in globals():
        return
    try:
        text_measurements.config(state="normal")
        text_measurements.insert(tk.END, f"BUF[{index}]: {formatted_value}\n")
        text_measurements.see(tk.END)
        text_measurements.config(state="disabled")
    except Exception:
        pass


def compute_voltage_for_index(index_zero_based):
    """Return the programmed voltage for a zero-based reading index."""
    single_run = sweep_state["single_run_voltages"]
    points = sweep_state["points_per_run"]
    if not single_run or points == 0:
        return 0.0
    return single_run[index_zero_based % points]


def reset_plot():
    """Clear live plot data."""
    global run_traces, run_color_cycle
    if "ax" not in globals():
        return
    ax.clear()
    ax.set_title("Voltage vs Current")
    ax.set_xlabel("Voltage (V)")
    ax.set_ylabel("Current (A)")
    ax.grid(True)
    run_traces.clear()
    run_color_cycle = cycle(RUN_COLORS)
    if "canvas" in globals():
        canvas.draw_idle()


def ensure_run_trace(run_index):
    """Return (creating if needed) the trace structure for the specified run index."""
    global run_traces, run_color_cycle
    if "ax" not in globals():
        return None
    while len(run_traces) <= run_index:
        color = next(run_color_cycle)
        label = f"Run {len(run_traces) + 1}"
        (line,) = ax.plot([], [], marker="o", linestyle="-", color=color, label=label)
        run_traces.append({"voltages": [], "currents": [], "line": line})
        ax.legend()
    return run_traces[run_index]


def refresh_axes():
    if "ax" in globals():
        ax.relim()
        ax.autoscale_view()
        if "canvas" in globals():
            canvas.draw_idle()


def rebuild_plot_from_cache():
    """Reconstruct plot traces from cached measurement values."""
    points_per_run = sweep_state["points_per_run"] or len(sweep_state["single_run_voltages"])
    if points_per_run <= 0:
        return
    reset_plot()
    for idx, current in enumerate(measurement_values, start=1):
        run_idx = (idx - 1) // points_per_run
        trace = ensure_run_trace(run_idx)
        if trace is None:
            continue
        voltage = compute_voltage_for_index(idx - 1)
        trace["voltages"].append(voltage)
        trace["currents"].append(current)
        trace["line"].set_data(trace["voltages"], trace["currents"])
    refresh_axes()


def append_point_to_plot(run_idx, voltage, current):
    trace = ensure_run_trace(run_idx)
    if trace is None:
        return
    trace["voltages"].append(voltage)
    trace["currents"].append(current)
    trace["line"].set_data(trace["voltages"], trace["currents"])
    refresh_axes()


def fetch_new_measurements(target_count):
    """Pull new readings from the nvbuffer and update displays."""
    global measurements, measurement_values
    if inst is None:
        return
    points_per_run = sweep_state["points_per_run"] or len(sweep_state["single_run_voltages"])
    start = len(measurement_values) + 1
    if target_count < start:
        return
    for idx in range(start, target_count + 1):
        reading = inst.query(f"print(smua.nvbuffer1.readings[{idx}])").strip()
        try:
            reading = float(reading)
        except ValueError as exc:
            raise RuntimeError(f"Invalid current value at index {idx}: {reading}") from exc
        measurement_values.append(reading)
        formatted = format_si_units(reading, "A")
        measurements.append(formatted)
        append_measurement_display(idx, formatted)
        if points_per_run > 0:
            run_idx = (idx - 1) // points_per_run
        else:
            run_idx = 0
        voltage = compute_voltage_for_index(idx - 1)
        append_point_to_plot(run_idx, voltage, reading)


def generate_voltage_series(count):
    """Return the voltage sequence for the first `count` measurements."""
    if count <= 0:
        return []
    single_run = sweep_state["single_run_voltages"]
    points = sweep_state["points_per_run"]
    if single_run and points:
        return [single_run[i % points] for i in range(count)]
    try:
        dynamic = compute_single_run_voltages()
    except Exception:
        return [0.0] * count
    if not dynamic:
        return [0.0] * count
    voltages = []
    repeats_needed = math.ceil(count / len(dynamic))
    for _ in range(repeats_needed):
        voltages.extend(dynamic)
        if len(voltages) >= count:
            break
    return voltages[:count]


def parse_formatted_current(value):
    """Convert a formatted current string into a float."""
    if isinstance(value, (int, float)):
        return float(value)
    if "µA" in value:
        return float(value.replace(" µA", "")) * 1e-6
    if "mA" in value:
        return float(value.replace(" mA", "")) * 1e-3
    if "A" in value:
        return float(value.replace(" A", ""))
    return float(value)

def cancel_monitor_job():
    """Cancel any scheduled sweep progress monitor callback."""
    job = sweep_state.get("monitor_job")
    if job is not None and "root" in globals():
        try:
            root.after_cancel(job)
        except Exception:
            pass
    sweep_state["monitor_job"] = None


def reset_sweep_state():
    """Clear sweep bookkeeping and restore button state."""
    cancel_monitor_job()
    sweep_state.update(
        {
            "configured": False,
            "running": False,
            "single_run_voltages": [],
            "points_per_run": 0,
            "start_voltage": 0.0,
            "stop_voltage": 0.0,
            "current_index": 0,
            "total_points": 0,
            "compliance": None,
            "total_runs": 0,
            "inputs_snapshot": None,
            "elapsed_time": 0.0,
            "segment_start": None,
            "pending_points": 0,
            "segment_points": 0,
            "segment_start_index": 0,
            "timer_started": False,
        }
    )
    clear_measurement_records()
    try:
        reset_plot()
    except Exception:
        pass
    if "btn_start_sweep" in globals():
        try:
            btn_start_sweep.config(state="normal")
        except Exception:
            pass
    if "btn_stop_sweep" in globals():
        try:
            btn_stop_sweep.config(state="disabled")
        except Exception:
            pass


def launch_next_segment():
    """Program and begin the next sweep segment, returning True if initiated."""
    if inst is None:
        return False
    points_per_run = sweep_state["points_per_run"]
    if points_per_run <= 0:
        raise RuntimeError("Sweep has no configured points.")
    remaining_points = sweep_state["pending_points"]
    if remaining_points <= 0:
        return False

    offset = sweep_state["current_index"] % points_per_run
    if offset < 0:
        offset = 0
    points_this_cycle = points_per_run - offset if offset else points_per_run
    segment_points = min(points_this_cycle, remaining_points)
    if segment_points <= 0:
        return False

    segment_values = sweep_state["single_run_voltages"][offset : offset + segment_points]
    values_str = ",".join(f"{value:.12g}" for value in segment_values)
    inst.write(f"smua.trigger.source.listv({{{values_str}}})")
    inst.write(f"smua.trigger.count = {segment_points}")
    inst.write("smua.trigger.arm.count = 1")
    inst.write("smua.trigger.source.action = smua.ENABLE")
    inst.write("smua.trigger.measure.action = smua.ENABLE")
    inst.write("smua.trigger.measure.stimulus = smua.trigger.SOURCE_COMPLETE_EVENT_ID")
    if not sweep_state["timer_started"]:
        inst.write("timer.reset()")
        sweep_state["timer_started"] = True
    inst.write("smua.source.output = smua.OUTPUT_ON")
    inst.write("smua.trigger.initiate()")

    sweep_state["segment_points"] = segment_points
    sweep_state["segment_start_index"] = sweep_state["current_index"]
    sweep_state["pending_points"] -= segment_points
    sweep_state["running"] = True
    sweep_state["segment_start"] = time.perf_counter()

    btn_start_sweep.config(state="disabled")
    btn_stop_sweep.config(state="normal")
    status_var.set(
        f"Sweep running: {sweep_state['current_index']} / {sweep_state['total_points']} point(s)"
    )
    schedule_progress_monitor()
    return True


def update_progress_from_buffer():
    """Query buffer depth and refresh sweep progress bookkeeping."""
    count_str = inst.query("print(smua.nvbuffer1.n)").strip()
    try:
        count = int(float(count_str))
    except ValueError as exc:
        raise RuntimeError(f"Unexpected buffer count: {count_str}") from exc
    fetch_new_measurements(count)
    sweep_state["current_index"] = min(count, sweep_state["total_points"])
    return sweep_state["current_index"]


def schedule_progress_monitor(delay_ms=None):
    """Schedule the next sweep progress poll."""
    if "root" not in globals():
        return
    if delay_ms is None:
        delay_ms = compute_poll_interval_ms()
    cancel_monitor_job()
    sweep_state["monitor_job"] = root.after(delay_ms, poll_sweep_progress)


def poll_sweep_progress():
    """Periodically check sweep status so GUI stays informed."""
    sweep_state["monitor_job"] = None
    if inst is None or not sweep_state["running"]:
        return
    try:
        completed = update_progress_from_buffer()
        total = sweep_state["total_points"]
        status_var.set(f"Sweep running: {completed} / {total} point(s)")

        segment_points = sweep_state["segment_points"]
        progressed = completed - sweep_state["segment_start_index"]
        if segment_points > 0 and progressed >= segment_points:
            if sweep_state["segment_start"] is not None:
                sweep_state["elapsed_time"] += time.perf_counter() - sweep_state["segment_start"]
                sweep_state["segment_start"] = None
            sweep_state["segment_points"] = 0
            sweep_state["segment_start_index"] = completed
            if sweep_state["pending_points"] > 0:
                if not launch_next_segment():
                    status_var.set("Failed to start next sweep segment.")
                    schedule_progress_monitor(1000)
                return
            if completed >= total:
                finalize_sweep_completion()
                return
        if completed >= total:
            finalize_sweep_completion()
        else:
            schedule_progress_monitor()
    except Exception as exc:
        status_var.set(f"Sweep monitor error: {exc}")
        schedule_progress_monitor(1000)


def finalize_sweep_completion():
    """Handle successful completion of the programmed sweep."""
    if not sweep_state["running"]:
        return
    sweep_state["running"] = False
    try:
        update_progress_from_buffer()
    except Exception:
        pass
    sweep_state["current_index"] = sweep_state["total_points"]
    if sweep_state["segment_start"] is not None:
        sweep_state["elapsed_time"] += time.perf_counter() - sweep_state["segment_start"]
        sweep_state["segment_start"] = None
    sweep_state["pending_points"] = 0
    sweep_state["segment_points"] = 0
    sweep_state["segment_start_index"] = sweep_state["total_points"]
    sweep_state["timer_started"] = False
    cancel_monitor_job()
    total_ms = sweep_state["elapsed_time"] * 1000.0
    try:
        inst.write("smua.source.output = smua.OUTPUT_OFF")
    except Exception:
        pass
    if "btn_start_sweep" in globals():
        try:
            btn_start_sweep.config(state="normal")
        except Exception:
            pass
    if "btn_stop_sweep" in globals():
        try:
            btn_stop_sweep.config(state="disabled")
        except Exception:
            pass
    status_var.set(f"Sweep completed in {total_ms:.2f} ms")
    try:
        messagebox.showinfo(
            "Sweep Completed",
            (
                f"Voltage sweep completed successfully.\n"
                f"Total runs: {sweep_state['total_runs']}\n"
                f"Elapsed time: {total_ms:.2f} ms."
            ),
        )
    except Exception:
        pass


def configure_trigger_model(single_run_voltages, compliance, total_runs, snapshot):
    """Push a fresh sweep definition into the instrument trigger model."""
    global measurements
    if inst is None:
        raise RuntimeError("Instrument is not connected.")
    if not single_run_voltages:
        raise ValueError("Voltage sweep has no points.")

    inst.write("smua.abort()")
    inst.write("smua.reset()")
    inst.write("smua.nvbuffer1.clear()")
    inst.write("smua.nvbuffer1.appendmode = 1")
    inst.write("smua.source.func = smua.OUTPUT_DCVOLTS")
    inst.write(f"smua.source.limiti = {compliance}")
    inst.write("smua.source.output = smua.OUTPUT_OFF")
    inst.write("smua.trigger.source.action = smua.ENABLE")
    inst.write("smua.trigger.source.stimulus = 0")
    inst.write("smua.trigger.measure.action = smua.ENABLE")
    inst.write("smua.trigger.measure.stimulus = smua.trigger.SOURCE_COMPLETE_EVENT_ID")
    inst.write("smua.trigger.measure.i(smua.nvbuffer1)")
    inst.write(f"smua.measure.delay = {MEASUREMENT_DELAY_SECONDS}")
    inst.write("smua.trigger.arm.count = 1")
    inst.write("smua.trigger.count = 1")

    cancel_monitor_job()
    total_points = len(single_run_voltages) * total_runs
    sweep_state.update(
        {
            "configured": True,
            "running": False,
            "single_run_voltages": list(single_run_voltages),
            "points_per_run": len(single_run_voltages),
            "start_voltage": single_run_voltages[0],
            "stop_voltage": single_run_voltages[-1],
            "current_index": 0,
            "total_points": total_points,
            "compliance": compliance,
            "total_runs": total_runs,
            "inputs_snapshot": snapshot,
            "elapsed_time": 0.0,
            "segment_start": None,
            "pending_points": 0,
            "segment_points": 0,
            "segment_start_index": 0,
            "timer_started": False,
        }
    )
    clear_measurement_records()
    try:
        reset_plot()
    except Exception:
        pass
    status_var.set(f"Sweep prepared: {total_points} point(s) ready")
    if "btn_start_sweep" in globals():
        try:
            btn_start_sweep.config(state="normal")
        except Exception:
            pass
    if "btn_stop_sweep" in globals():
        try:
            btn_stop_sweep.config(state="disabled")
        except Exception:
            pass

# Connect to the instrument
def connect():
    global inst
    try:
        if inst is None:
            inst = rm.open_resource(ADDRESS)
            inst.timeout = 30000
            inst.read_termination = "\n"
            inst.write_termination = "\n"
        status_var.set(f"Connected: {ADDRESS}")
        btn_connect.config(state="disabled")
        btn_disconnect.config(state="normal")
    except Exception as e:
        messagebox.showerror("Connection Error", str(e))
        status_var.set("Connection Failed")

# Disconnect from the instrument
def disconnect():
    global inst
    try:
        if inst is not None:
            inst.write("smua.source.output = smua.OUTPUT_OFF")  # Turn off output before disconnecting
            inst.close()
            inst = None
        reset_sweep_state()
        status_var.set("Disconnected")
        btn_connect.config(state="normal")
        btn_disconnect.config(state="disabled")
    except Exception as e:
        messagebox.showerror("Disconnection Error", str(e))

# Start or resume a trigger-controlled sweep sequence
def start_sweep():
    global inst
    if inst is None:
        messagebox.showwarning("Not Connected", "Please connect to the instrument first.")
        return
    try:
        compliance = float(entry_compliance.get())
        total_runs = parse_total_runs()
        single_run_voltages = compute_single_run_voltages()
        snapshot = {
            "voltages": tuple(single_run_voltages),
            "compliance": compliance,
            "total_runs": total_runs,
        }

        needs_new_configuration = (
            not sweep_state["configured"]
            or sweep_state["inputs_snapshot"] != snapshot
            or sweep_state["current_index"] >= sweep_state["total_points"]
        )
        if needs_new_configuration:
            configure_trigger_model(single_run_voltages, compliance, total_runs, snapshot)

        if sweep_state["running"]:
            status_var.set("Sweep already running")
            return

        try:
            update_progress_from_buffer()
        except Exception:
            pass
        remaining_points = sweep_state["total_points"] - sweep_state["current_index"]
        if remaining_points <= 0:
            messagebox.showinfo(
                "Sweep Complete",
                "The configured sweep has already finished. Adjust the sweep parameters to start again.",
            )
            return
        sweep_state["pending_points"] = remaining_points
        sweep_state["segment_points"] = 0
        sweep_state["segment_start_index"] = sweep_state["current_index"]
        sweep_state["segment_start"] = None
        sweep_state["timer_started"] = False
        if not launch_next_segment():
            raise RuntimeError("Unable to begin sweep segment.")
    except ValueError as ve:
        messagebox.showerror("Input Error", f"Invalid input: {ve}")
    except Exception as exc:
        sweep_state["running"] = False
        sweep_state["segment_start"] = None
        btn_start_sweep.config(state="normal")
        btn_stop_sweep.config(state="disabled")
        status_var.set("Sweep start failed")
        messagebox.showerror("Sweep Error", str(exc))


def stop_sweep():
    """Abort the active sweep and preserve progress for later resumption."""
    global inst
    if inst is None or not sweep_state["configured"]:
        return
    if not sweep_state["running"]:
        status_var.set("Sweep already paused")
        return
    try:
        inst.write("smua.abort()")
    except Exception as exc:
        status_var.set(f"Stop command error: {exc}")
    try:
        completed = update_progress_from_buffer()
    except Exception:
        completed = sweep_state["current_index"]
    segment_completed = max(completed - sweep_state["segment_start_index"], 0)
    remaining_in_segment = max(sweep_state["segment_points"] - segment_completed, 0)
    sweep_state["pending_points"] += remaining_in_segment
    sweep_state["segment_points"] = 0
    sweep_state["segment_start_index"] = completed
    sweep_state["running"] = False
    if sweep_state["segment_start"] is not None:
        sweep_state["elapsed_time"] += time.perf_counter() - sweep_state["segment_start"]
        sweep_state["segment_start"] = None
    sweep_state["timer_started"] = False
    cancel_monitor_job()
    btn_start_sweep.config(state="normal")
    btn_stop_sweep.config(state="disabled")
    total = sweep_state["total_points"]
    status_var.set(f"Sweep paused at point {completed} of {total}")

# Function to save measurements to a CSV file with voltages matched to currents
def save_measurements_to_csv():
    global measurements, measurement_values
    total = len(measurement_values) if measurement_values else len(measurements)
    if total == 0:
        messagebox.showwarning("No Data", "No measurements to save. Please fetch measurements first.")
        return
    try:
        if measurement_values:
            numeric_currents = list(measurement_values)
        else:
            numeric_currents = []
            for current in measurements:
                try:
                    numeric_currents.append(parse_formatted_current(current))
                except ValueError:
                    messagebox.showerror("Save Error", f"Invalid current value: {current}")
                    return
        voltages = generate_voltage_series(total)

        # Save to CSV
        filename = "measurements.csv"
        with open(filename, mode="w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["Voltage (V)", "Current (A)"])  # Write the header
            for v, m in zip(voltages, numeric_currents):
                writer.writerow([v, m])  # Write each voltage-current pair
        messagebox.showinfo("File Saved", f"Measurements saved to {filename}")
    except Exception as e:
        messagebox.showerror("Save Error", f"An error occurred while saving the file:\n{str(e)}")

# Fetch all measurements from the buffer
def fetch_all_measurements():
    global inst, measurements
    if inst is None:
        messagebox.showwarning("Not Connected", "Please connect to the instrument first.")
        return
    try:
        # Start timing the measurement
        measure_start_time = time.time()

        # Query the number of readings in the buffer
        buffer_count = inst.query("print(smua.nvbuffer1.n)").strip()
        try:
            buffer_count = int(float(buffer_count))  # Convert to integer after handling potential float strings
        except ValueError:
            messagebox.showerror("Fetch Error", f"Unexpected buffer count: {buffer_count}")
            return

        if buffer_count == 0:
            messagebox.showinfo("Buffer Empty", "No measurements in the buffer.")
            return

        # Fetch all readings
        new_values = []
        new_formatted = []
        for i in range(1, buffer_count + 1):
            current = inst.query(f"print(smua.nvbuffer1.readings[{i}])").strip()
            try:
                current = float(current)  # Ensure the current value is a valid float
            except ValueError:
                messagebox.showerror("Fetch Error", f"Invalid current value: {current}")
                return
            new_values.append(current)
            new_formatted.append(format_si_units(current, "A"))

        measurement_values[:] = new_values
        measurements[:] = new_formatted

        # End timing the measurement
        measure_end_time = time.time()
        measure_time_ms = (measure_end_time - measure_start_time) * 1000  # Convert to milliseconds

        # Update the text widget with all measurements
        update_measurements_display(measurements)

        # Automatically match voltages to currents
        match_voltages_to_currents()
        rebuild_plot_from_cache()

        # Display the measurement time
        status_var.set(f"Measurements fetched in {measure_time_ms:.2f} ms")
        messagebox.showinfo("Fetch Completed", f"Measurements fetched successfully in {measure_time_ms:.2f} ms.")
    except Exception as e:
        messagebox.showerror("Fetch Error", str(e))

# Function to match voltages with currents and display them
def match_voltages_to_currents():
    global measurements, measurement_values
    count = len(measurement_values)
    if count == 0:
        if not measurements:
            messagebox.showwarning("No Data", "No measurements to match. Please fetch measurements first.")
            return
        # Attempt to parse formatted strings if numeric values are absent.
        parsed = []
        for current in measurements:
            try:
                parsed.append(parse_formatted_current(current))
            except ValueError:
                messagebox.showerror("Match Error", f"Invalid current value: {current}")
                return
        measurement_values[:] = parsed
        count = len(measurement_values)
    if count == 0:
        messagebox.showwarning("No Data", "No measurements available for matching.")
        return

    try:
        voltages = generate_voltage_series(count)
        # Ensure formatted values list aligns with numeric data
        if len(measurements) < count:
            measurements.extend(
                format_si_units(value, "A") for value in measurement_values[len(measurements):]
            )

        text_measurements.config(state="normal")
        text_measurements.delete(1.0, tk.END)
        pairs = []
        for idx in range(count):
            voltage = voltages[idx]
            current_str = measurements[idx] if idx < len(measurements) else format_si_units(
                measurement_values[idx], "A"
            )
            text_measurements.insert(tk.END, f"V={voltage:.3f} V, I={current_str}\n")
            pairs.append((voltage, current_str))
        text_measurements.config(state="disabled")
        return pairs
    except Exception as e:
        messagebox.showerror("Match Error", f"An error occurred while matching voltages to currents:\n{str(e)}")

# Function to plot measurements
def plot_measurements():
    global measurements, measurement_values
    count = len(measurement_values)
    if count == 0:
        if not measurements:
            messagebox.showwarning("No Data", "No measurements to plot. Please fetch measurements first.")
            return
        parsed = []
        for current in measurements:
            try:
                parsed.append(parse_formatted_current(current))
            except ValueError:
                messagebox.showerror("Plot Error", f"Invalid current value: {current}")
                return
        measurement_values[:] = parsed
        count = len(measurement_values)
    if count == 0:
        messagebox.showwarning("No Data", "No measurements to plot.")
        return

    try:
        voltages = generate_voltage_series(count)
        if len(measurements) < count:
            measurements.extend(
                format_si_units(value, "A") for value in measurement_values[len(measurements):]
            )
        line = ensure_plot_line()
        if line is None or "canvas" not in globals():
            return
        line.set_data(voltages, measurement_values[:count])
        ax.relim()
        ax.autoscale_view()
        canvas.draw()
    except Exception as e:
        messagebox.showerror("Plot Error", f"An error occurred while plotting:\n{str(e)}")

# GUI setup
root = tk.Tk()
root.title("Keithley 2602B Control - PyVISA GUI")

CONTROL_FONT = ("Segoe UI", 11)
BUTTON_FONT = ("Segoe UI", 11)
STATUS_FONT = ("Segoe UI", 10)
TEXT_FONT = ("Consolas", 10)

root.grid_columnconfigure(0, weight=0)
root.grid_columnconfigure(1, weight=1)
root.grid_rowconfigure(0, weight=1)

left_frame = tk.Frame(root)
left_frame.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
left_frame.grid_columnconfigure(0, weight=0)
left_frame.grid_columnconfigure(1, weight=1)
left_frame.grid_rowconfigure(11, weight=1)

# Voltage sweep inputs
tk.Label(left_frame, text="Start Voltage (V):", font=CONTROL_FONT).grid(row=0, column=0, sticky="e", padx=5, pady=8)
entry_start_voltage = tk.Entry(left_frame, font=CONTROL_FONT)
entry_start_voltage.insert(0, "0.0")  # Default start voltage
entry_start_voltage.grid(row=0, column=1, padx=5, pady=8, sticky="ew", ipady=4)

tk.Label(left_frame, text="Stop Voltage (V):", font=CONTROL_FONT).grid(row=1, column=0, sticky="e", padx=5, pady=8)
entry_stop_voltage = tk.Entry(left_frame, font=CONTROL_FONT)
entry_stop_voltage.insert(0, "3.0")  # Default stop voltage
entry_stop_voltage.grid(row=1, column=1, padx=5, pady=8, sticky="ew", ipady=4)

tk.Label(left_frame, text="Step Voltage (V):", font=CONTROL_FONT).grid(row=2, column=0, sticky="e", padx=5, pady=8)
entry_step_voltage = tk.Entry(left_frame, font=CONTROL_FONT)
entry_step_voltage.insert(0, "1.0")  # Default step voltage
entry_step_voltage.grid(row=2, column=1, padx=5, pady=8, sticky="ew", ipady=4)

# Compliance current input
tk.Label(left_frame, text="Compliance (A):", font=CONTROL_FONT).grid(row=3, column=0, sticky="e", padx=5, pady=8)
entry_compliance = tk.Entry(left_frame, font=CONTROL_FONT)
entry_compliance.insert(0, "0.5")  # Default compliance current
entry_compliance.grid(row=3, column=1, padx=5, pady=8, sticky="ew", ipady=4)

tk.Label(left_frame, text="Total Runs:", font=CONTROL_FONT).grid(row=4, column=0, sticky="e", padx=5, pady=8)
entry_total_runs = tk.Entry(left_frame, font=CONTROL_FONT)
entry_total_runs.insert(0, "1")
entry_total_runs.grid(row=4, column=1, padx=5, pady=8, sticky="ew", ipady=4)

# Connect button
btn_connect = tk.Button(left_frame, text="Connect", command=connect, font=BUTTON_FONT)
btn_connect.grid(row=5, column=0, padx=5, pady=8, sticky="ew", ipady=5)

# Disconnect button
btn_disconnect = tk.Button(left_frame, text="Disconnect", command=disconnect, state="disabled", font=BUTTON_FONT)
btn_disconnect.grid(row=5, column=1, padx=5, pady=8, sticky="ew", ipady=5)

# Start sweep button
btn_start_sweep = tk.Button(left_frame, text="Start Sweep", command=start_sweep, font=BUTTON_FONT)
btn_start_sweep.grid(row=6, column=0, padx=5, pady=8, sticky="ew", ipady=5)

# Stop sweep button
btn_stop_sweep = tk.Button(left_frame, text="Stop Sweep", command=stop_sweep, state="disabled", font=BUTTON_FONT)
btn_stop_sweep.grid(row=6, column=1, padx=5, pady=8, sticky="ew", ipady=5)

# Fetch all measurements button
btn_fetch_all = tk.Button(left_frame, text="Fetch All Measurements", command=fetch_all_measurements, font=BUTTON_FONT)
btn_fetch_all.grid(row=7, column=0, padx=5, pady=8, sticky="ew", ipady=5)

# Save to CSV button
btn_save_csv = tk.Button(left_frame, text="Save to CSV", command=save_measurements_to_csv, font=BUTTON_FONT)
btn_save_csv.grid(row=7, column=1, padx=5, pady=8, sticky="ew", ipady=5)

# Status label
status_var = tk.StringVar(value="Disconnected")
tk.Label(left_frame, textvariable=status_var, font=STATUS_FONT).grid(row=9, column=0, columnspan=2, pady=10)

# Measurements display
tk.Label(left_frame, text="Measurements:", font=CONTROL_FONT).grid(row=10, column=0, columnspan=2, pady=5)
text_measurements = tk.Text(left_frame, height=8, width=50, state="disabled", font=TEXT_FONT)  # Create a text widget
text_measurements.grid(row=11, column=0, columnspan=2, padx=5, pady=5, sticky="nsew")

plot_frame = tk.Frame(root)
plot_frame.grid(row=0, column=1, padx=5, pady=5, sticky="nsew")
fig = Figure(figsize=(5, 4), dpi=100)
ax = fig.add_subplot(111)
ax.set_title("Voltage vs Current")
ax.set_xlabel("Voltage (V)")
ax.set_ylabel("Current (A)")
canvas = FigureCanvasTkAgg(fig, master=plot_frame)
canvas.draw()
canvas.get_tk_widget().pack(fill="both", expand=True)

# Function to update the text widget with measurements
def update_measurements_display(measurements):
    text_measurements.config(state="normal")  # Enable editing
    text_measurements.delete(1.0, tk.END)  # Clear the text widget
    for i, m in enumerate(measurements):
        text_measurements.insert(tk.END, f"BUF[{i+1}]: {m}\n")  # Add each measurement
    text_measurements.config(state="disabled")  # Disable editing

# Handle window close
def on_close():
    try:
        disconnect()
    except Exception:
        pass
    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_close)
root.mainloop()
