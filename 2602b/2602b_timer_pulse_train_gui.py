import tkinter as tk
from tkinter import messagebox
import pyvisa

# Default VISA resource address for the 2602B; adjust as needed.
ADDRESS = "TCPIP0::169.254.0.1::5025::SOCKET"

rm = pyvisa.ResourceManager()
inst = None


def connect():
    global inst
    if inst is not None:
        messagebox.showinfo("Already Connected", "Instrument connection is already open.")
        return
    try:
        resource = entry_address.get().strip() or ADDRESS
        status_var.set("Connecting...")
        root.update_idletasks()
        inst_handle = rm.open_resource(resource)
        inst_handle.timeout = 10000
        inst = inst_handle
        status_var.set(f"Connected: {resource}")
        btn_connect.config(state="disabled")
        btn_disconnect.config(state="normal")
        btn_run.config(state="normal")
    except Exception as exc:
        status_var.set("Disconnected")
        messagebox.showerror("Connection Error", f"Failed to connect to instrument:\n{exc}")


def disconnect():
    global inst
    if inst is None:
        status_var.set("Disconnected")
        return
    try:
        inst.close()
    except Exception:
        pass
    finally:
        inst = None
        status_var.set("Disconnected")
        btn_connect.config(state="normal")
        btn_disconnect.config(state="disabled")
        btn_run.config(state="disabled")


def validate_inputs():
    try:
        pulse_level = float(entry_pulse_level.get())
        pulse_width_us = float(entry_pulse_width.get())
        pulse_period_us = float(entry_pulse_period.get())
        bias_level = float(entry_bias_level.get())
        current_limit = float(entry_current_limit.get())
        pulse_count = int(float(entry_pulse_count.get()))
        period_timer_index = int(float(entry_period_timer_index.get()))
        pulse_timer_index = int(float(entry_pulse_timer_index.get()))
    except ValueError as exc:
        raise ValueError("All numeric fields must contain valid numbers.") from exc

    if pulse_count <= 0:
        raise ValueError("Pulse count must be greater than zero.")
    if pulse_width_us <= 0:
        raise ValueError("Pulse width (us) must be greater than zero.")
    if pulse_period_us <= 0:
        raise ValueError("Pulse period (us) must be greater than zero.")
    if pulse_period_us < pulse_width_us:
        raise ValueError("Pulse period must be greater than or equal to pulse width.")
    if period_timer_index <= 0 or pulse_timer_index <= 0:
        raise ValueError("Timer indexes must be positive integers.")

    return {
        "pulse_level": pulse_level,
        "pulse_width_us": pulse_width_us,
        "pulse_period_us": pulse_period_us,
        "bias_level": bias_level,
        "current_limit": current_limit,
        "pulse_count": pulse_count,
        "period_timer_index": period_timer_index,
        "pulse_timer_index": pulse_timer_index,
    }


def compute_source_range(pulse_level, bias_level):
    source_range = max(abs(bias_level), abs(pulse_level))
    if source_range == 0:
        source_range = 0.2
    return source_range


def run_pulse_train():
    try:
        params = validate_inputs()
    except ValueError as exc:
        messagebox.showerror("Input Error", str(exc))
        return

    if inst is None:
        messagebox.showwarning("Not Connected", "Connect to the instrument before running the pulse train.")
        return

    instrument = inst
    pulse_width_s = params["pulse_width_us"] * 1e-6
    pulse_period_s = params["pulse_period_us"] * 1e-6
    period_timer_count = max(params["pulse_count"] - 1, 0)
    source_range = compute_source_range(params["pulse_level"], params["bias_level"])

    output_enabled = False
    try:
        status_var.set("Configuring pulse train...")
        root.update_idletasks()

        # Reset and set up source function.
        instrument.write("reset()")
        instrument.write("smua.source.func = smua.OUTPUT_DCVOLTS")
        instrument.write(f"smua.source.rangev = {source_range:.9f}")
        instrument.write(f"smua.source.levelv = {params['bias_level']:.9f}")
        instrument.write(f"smua.source.limiti = {params['current_limit']:.9f}")

        # Configure timers.
        instrument.write(
            f"trigger.timer[{params['period_timer_index']}].delay = {pulse_period_s:.9f}"
        )
        instrument.write(
            f"trigger.timer[{params['period_timer_index']}].count = {period_timer_count}"
        )
        instrument.write(
            f"trigger.timer[{params['period_timer_index']}].passthrough = true"
        )
        instrument.write(
            f"trigger.timer[{params['period_timer_index']}].stimulus = smua.trigger.ARMED_EVENT_ID"
        )

        instrument.write(
            f"trigger.timer[{params['pulse_timer_index']}].delay = {pulse_width_s:.9f}"
        )
        instrument.write(
            f"trigger.timer[{params['pulse_timer_index']}].count = 1"
        )
        instrument.write(
            f"trigger.timer[{params['pulse_timer_index']}].passthrough = false"
        )
        instrument.write(
            f"trigger.timer[{params['pulse_timer_index']}].stimulus = trigger.timer[{params['period_timer_index']}].EVENT_ID"
        )

        # Configure trigger model identical to TSP helper.
        instrument.write(
            f"smua.trigger.source.listv({{{params['pulse_level']:.9f}}})"
        )
        instrument.write("smua.trigger.source.action = smua.ENABLE")
        instrument.write(
            f"smua.trigger.source.stimulus = trigger.timer[{params['period_timer_index']}].EVENT_ID"
        )
        instrument.write("smua.trigger.measure.action = smua.DISABLE")
        instrument.write(f"smua.trigger.source.limiti = {params['current_limit']:.9f}")
        instrument.write(f"smua.measure.rangei = {params['current_limit']:.9f}")
        instrument.write("smua.trigger.endpulse.action = smua.SOURCE_IDLE")
        instrument.write(
            f"smua.trigger.endpulse.stimulus = trigger.timer[{params['pulse_timer_index']}].EVENT_ID"
        )
        instrument.write("smua.trigger.arm.count = 1")
        instrument.write(f"smua.trigger.count = {params['pulse_count']}")

        # Run pulse train.
        status_var.set("Running pulse train...")
        root.update_idletasks()
        instrument.write("smua.source.output = smua.OUTPUT_ON")
        output_enabled = True
        instrument.write("smua.trigger.initiate()")
        instrument.write("waitcomplete()")

        status_message = (
            "Completed pulse train: "
            f"level={params['pulse_level']} V, "
            f"width={params['pulse_width_us']} us, "
            f"period={params['pulse_period_us']} us, "
            f"count={params['pulse_count']}, "
            f"bias={params['bias_level']} V, "
            f"limit={params['current_limit']} A"
        )
        status_var.set(status_message)
        messagebox.showinfo("Pulse Train Complete", status_message)
    except Exception as exc:
        status_var.set("Error during pulse train configuration.")
        messagebox.showerror("Instrument Error", f"Failed to run pulse train:\n{exc}")
    finally:
        if output_enabled and inst is not None:
            try:
                inst.write("smua.source.output = smua.OUTPUT_OFF")
            except Exception:
                pass


root = tk.Tk()
root.title("Keithley 2602B Pulse Train GUI")

CONTROL_FONT = ("Segoe UI", 11)
BUTTON_FONT = ("Segoe UI", 11)
STATUS_FONT = ("Segoe UI", 10)

root.grid_columnconfigure(0, weight=1)

frame = tk.Frame(root)
frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
frame.grid_columnconfigure(1, weight=1)

tk.Label(frame, text="VISA Address:", font=CONTROL_FONT).grid(row=0, column=0, sticky="e", padx=5, pady=4)
entry_address = tk.Entry(frame, font=CONTROL_FONT)
entry_address.insert(0, ADDRESS)
entry_address.grid(row=0, column=1, padx=5, pady=4, sticky="ew")

tk.Label(frame, text="Pulse Level (V):", font=CONTROL_FONT).grid(row=1, column=0, sticky="e", padx=5, pady=4)
entry_pulse_level = tk.Entry(frame, font=CONTROL_FONT)
entry_pulse_level.insert(0, "5.0")
entry_pulse_level.grid(row=1, column=1, padx=5, pady=4, sticky="ew")

tk.Label(frame, text="Pulse Width (us):", font=CONTROL_FONT).grid(row=2, column=0, sticky="e", padx=5, pady=4)
entry_pulse_width = tk.Entry(frame, font=CONTROL_FONT)
entry_pulse_width.insert(0, "600")
entry_pulse_width.grid(row=2, column=1, padx=5, pady=4, sticky="ew")

tk.Label(frame, text="Pulse Period (us):", font=CONTROL_FONT).grid(row=3, column=0, sticky="e", padx=5, pady=4)
entry_pulse_period = tk.Entry(frame, font=CONTROL_FONT)
entry_pulse_period.insert(0, "5000")
entry_pulse_period.grid(row=3, column=1, padx=5, pady=4, sticky="ew")

tk.Label(frame, text="Bias Level (V):", font=CONTROL_FONT).grid(row=4, column=0, sticky="e", padx=5, pady=4)
entry_bias_level = tk.Entry(frame, font=CONTROL_FONT)
entry_bias_level.insert(0, "0.0")
entry_bias_level.grid(row=4, column=1, padx=5, pady=4, sticky="ew")

tk.Label(frame, text="Current Limit (A):", font=CONTROL_FONT).grid(row=5, column=0, sticky="e", padx=5, pady=4)
entry_current_limit = tk.Entry(frame, font=CONTROL_FONT)
entry_current_limit.insert(0, "0.1")
entry_current_limit.grid(row=5, column=1, padx=5, pady=4, sticky="ew")

tk.Label(frame, text="Pulse Count:", font=CONTROL_FONT).grid(row=6, column=0, sticky="e", padx=5, pady=4)
entry_pulse_count = tk.Entry(frame, font=CONTROL_FONT)
entry_pulse_count.insert(0, "10")
entry_pulse_count.grid(row=6, column=1, padx=5, pady=4, sticky="ew")

tk.Label(frame, text="Period Timer Index:", font=CONTROL_FONT).grid(row=7, column=0, sticky="e", padx=5, pady=4)
entry_period_timer_index = tk.Entry(frame, font=CONTROL_FONT)
entry_period_timer_index.insert(0, "1")
entry_period_timer_index.grid(row=7, column=1, padx=5, pady=4, sticky="ew")

tk.Label(frame, text="Pulse Timer Index:", font=CONTROL_FONT).grid(row=8, column=0, sticky="e", padx=5, pady=4)
entry_pulse_timer_index = tk.Entry(frame, font=CONTROL_FONT)
entry_pulse_timer_index.insert(0, "2")
entry_pulse_timer_index.grid(row=8, column=1, padx=5, pady=4, sticky="ew")

btn_connect = tk.Button(frame, text="Connect", font=BUTTON_FONT, command=connect)
btn_connect.grid(row=9, column=0, padx=5, pady=8, sticky="ew")

btn_disconnect = tk.Button(frame, text="Disconnect", font=BUTTON_FONT, command=disconnect, state="disabled")
btn_disconnect.grid(row=9, column=1, padx=5, pady=8, sticky="ew")

btn_run = tk.Button(frame, text="Run Pulse Train", font=BUTTON_FONT, command=run_pulse_train, state="disabled")
btn_run.grid(row=10, column=0, columnspan=2, padx=5, pady=10, sticky="ew")

status_var = tk.StringVar(value="Disconnected")
tk.Label(frame, textvariable=status_var, font=STATUS_FONT, anchor="w").grid(row=11, column=0, columnspan=2, sticky="ew", padx=5, pady=5)


def on_close():
    try:
        disconnect()
    finally:
        root.destroy()


root.protocol("WM_DELETE_WINDOW", on_close)
root.mainloop()
