"""Tkinter GUI for controlling the measure-voltage.tsp script."""

import pathlib
import tkinter as tk
from tkinter import messagebox, ttk

import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import pyvisa
import sys


DEFAULT_ADDRESS = "TCPIP0::169.254.188.69::5025::SOCKET"
SCRIPT_NAME = "VoltmeterScript"
SCRIPT_FILE = pathlib.Path(__file__).with_name("test_2450_measure-voltage.tsp")


class VoltmeterGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("2450 Voltmeter")
        self.root.minsize(900, 650)

        self.rm: pyvisa.ResourceManager | None = None
        self.inst = None
        self.script_loaded = False

        self.address_var = tk.StringVar(value=DEFAULT_ADDRESS)
        self.samples_var = tk.StringVar(value="10")
        self.range_var = tk.StringVar(value="")
        self.nplc_var = tk.StringVar(value="0.01")

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
        for col in range(6):
            frame.columnconfigure(col, weight=1 if col not in (0, 4, 5) else 0)

        # Connection controls
        ttk.Label(frame, text="VISA address:").grid(column=0, row=0, sticky="w")
        ttk.Entry(frame, textvariable=self.address_var, width=45).grid(column=1, row=0, columnspan=3, sticky="ew", padx=(4, 8))
        ttk.Button(frame, text="Connect", command=self.connect).grid(column=4, row=0)
        ttk.Button(frame, text="Disconnect", command=self.disconnect).grid(column=5, row=0, padx=(6, 0))

        # Measurement parameters
        ttk.Label(frame, text="Samples:").grid(column=0, row=1, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=self.samples_var, width=10).grid(column=1, row=1, sticky="w", pady=(12, 0))

        ttk.Label(frame, text="Range (V, blank=auto):").grid(column=0, row=2, sticky="w")
        ttk.Entry(frame, textvariable=self.range_var, width=10).grid(column=1, row=2, sticky="w")

        ttk.Label(frame, text="NPLC:").grid(column=0, row=3, sticky="w")
        ttk.Entry(frame, textvariable=self.nplc_var, width=10).grid(column=1, row=3, sticky="w")

        ttk.Button(frame, text="Measure", command=self.measure).grid(column=0, row=4, pady=(12, 0), sticky="w")
        ttk.Button(frame, text="Output Off", command=self.output_off).grid(column=1, row=4, pady=(12, 0), sticky="w")

        # Output log
        self.output = tk.Text(frame, height=14, width=70, state=tk.DISABLED)
        self.output.grid(column=0, row=5, columnspan=6, sticky="nsew", pady=(12, 0))
        frame.rowconfigure(5, weight=1)

        # Plot
        plot_frame = ttk.LabelFrame(self.root, text="Voltage Samples")
        plot_frame.grid(column=0, row=1, sticky="nsew", padx=12, pady=(0, 12))
        self.root.rowconfigure(1, weight=3)
        plot_frame.columnconfigure(0, weight=1)
        plot_frame.rowconfigure(0, weight=1)

        self.figure, self.ax = plt.subplots(figsize=(8, 4.5))
        self.figure.subplots_adjust(left=0.1, right=0.97, bottom=0.15, top=0.9)
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
            self.inst.timeout = 15000
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
                self.inst.write("pcall(voltmeter_output_off)")
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
        if not SCRIPT_FILE.exists():
            messagebox.showerror("Script", f"TSP file not found: {SCRIPT_FILE}")
            return
        script_text = SCRIPT_FILE.read_text(encoding="utf-8")

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
            self.inst.write("pcall(voltmeter_output_off)")
            self.script_loaded = True
            self._log("TSP script loaded.")
        except pyvisa.VisaIOError as exc:
            messagebox.showerror("Script", f"Failed to load script: {exc}")
            self._log(f"Script load failed: {exc}")

    # --------------------------------------------------------------- measure --
    def measure(self) -> None:
        if self.inst is None:
            messagebox.showwarning("Measure", "Connect to the instrument first.")
            return
        if not self.script_loaded:
            self._load_script()
        try:
            samples = int(float(self.samples_var.get()))
        except ValueError:
            messagebox.showerror("Measure", "Samples must be numeric.")
            return
        try:
            range_arg = self._format_float_arg(self.range_var.get())
            nplc_arg = self._format_float_arg(self.nplc_var.get())
        except ValueError as exc:
            messagebox.showerror("Measure", str(exc))
            return

        try:
            response = self.inst.query(
                f"print(measure_voltage({samples}, {range_arg}, {nplc_arg}))"
            ).strip()
            self._log(f"Result: {response}")

            buffer_values = self.inst.query("printbuffer(1, defbuffer1.n, defbuffer1)").strip()
            voltages = self._parse_buffer(buffer_values)
            if voltages:
                self._log("Buffer voltages (V):")
                self._log(", ".join(f"{v:.6f}" for v in voltages))
                self._update_plot(voltages)
        except pyvisa.VisaIOError as exc:
            messagebox.showerror("Measure", f"Measurement failed: {exc}")
            self._log(f"Measurement failed: {exc}")

    def output_off(self) -> None:
        if self.inst is None:
            return
        try:
            self.inst.write("pcall(voltmeter_output_off)")
            self._log("Output turned off.")
        except pyvisa.VisaIOError as exc:
            self._log(f"Failed to turn output off: {exc}")

    # ----------------------------------------------------------------- utils --
    def _format_float_arg(self, value: str) -> str:
        text = value.strip()
        if not text:
            return "nil"
        try:
            float(text)
        except ValueError:
            raise ValueError(f"Invalid numeric value: {text}")
        return text

    def _log(self, message: str) -> None:
        self.output.configure(state=tk.NORMAL)
        self.output.insert(tk.END, message + "\n")
        self.output.see(tk.END)
        self.output.configure(state=tk.DISABLED)

    def _parse_buffer(self, buffer_text: str) -> list[float]:
        if not buffer_text:
            return []
        values: list[float] = []
        for token in buffer_text.replace("\n", ",").split(","):
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
                markersize=5,
                linewidth=1.5,
                color="tab:blue",
            )
            self.ax.fill_between(x_vals, voltages, color="tab:blue", alpha=0.1)
            self.ax.set_xlim(0.5, len(voltages) + 0.5)
        self.ax.set_title("Measured Voltages")
        self.canvas.draw_idle()

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
    VoltmeterGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
