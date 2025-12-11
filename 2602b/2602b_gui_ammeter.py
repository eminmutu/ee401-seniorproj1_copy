import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import pyvisa
from pyvisa import errors as visa_errors

# -----------------------------------------------------------------------------
# THE LUA SCRIPT DEFINITION FOR THE AMMETER FUNCTIONS
# -----------------------------------------------------------------------------
TSP_SCRIPT = """
loadscript AmmeterFunctions
    function StartAmmeterBurst(count)
        if count == nil then count = 20 end
        smua.reset()

        -- Speed and range settings tailored for current capture
        -- Using 100mA range to match your working test
        smua.measure.nplc = 0.001
        smua.measure.autozero = smua.AUTOZERO_OFF
        smua.measure.autorangei = smua.AUTORANGE_OFF
        smua.measure.rangei = 100e-3 
        smua.measure.delay = 0

        -- Source zero volts so the SMU behaves as an ammeter
        smua.source.func = smua.OUTPUT_DCVOLTS
        smua.source.rangev = 20
        smua.source.levelv = 0
        smua.source.limiti = 1

        -- Buffer and trigger configuration for current readings
        smua.nvbuffer1.clear()
        smua.nvbuffer1.appendmode = 1
        smua.nvbuffer1.collecttimestamps = 1
        smua.trigger.measure.i(smua.nvbuffer1)

        smua.trigger.count = count
        smua.trigger.source.action = smua.DISABLE
        smua.trigger.measure.action = smua.ENABLE
        smua.trigger.arm.stimulus = 0
        smua.trigger.source.stimulus = 0
        smua.trigger.measure.stimulus = 0

        -- REMOVED PRINT STATEMENT:
        -- We must NOT print here. Python is waiting for the buffer data query later.
        -- Printing here would cause Python to read this text instead of the buffer count,
        -- causing the synchronization to fail.
        
        smua.source.output = smua.OUTPUT_ON
        smua.trigger.initiate()
    end

    function GetAmmeterData()
        smua.source.output = smua.OUTPUT_OFF
        if smua.nvbuffer1.n > 0 then
            print("DataStart")
            printbuffer(1, smua.nvbuffer1.n, smua.nvbuffer1)
            print("DataEnd")
        else
            print("Error: Buffer is empty.")
        end
    end
endscript
"""


class KeithleyAmmeterApp:
    """Simple GUI that mirrors the voltmeter tool but for current measurements."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Keithley 2602B High-Speed Ammeter")
        self.root.geometry("1000x700")

        self.rm: pyvisa.ResourceManager | None = None
        self.inst: pyvisa.resources.MessageBasedResource | None = None
        self._bg_thread: threading.Thread | None = None
        self._expected_count: int | None = None
        self._stop_event = threading.Event()
        self._closing = False

        self.status_var = tk.StringVar(value="Not Connected")

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()

    def _build_ui(self) -> None:
        conn_frame = ttk.LabelFrame(self.root, text="Connection")
        conn_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(conn_frame, text="VISA Resource:").pack(side=tk.LEFT, padx=5)
        self.visa_entry = ttk.Entry(conn_frame, width=40)
        self.visa_entry.insert(0, "TCPIP0::169.254.0.1::5025::SOCKET")
        self.visa_entry.pack(side=tk.LEFT, padx=5)

        self.connect_btn = ttk.Button(conn_frame, text="Connect & Load Script", command=self.connect)
        self.connect_btn.pack(side=tk.LEFT, padx=5)

        ctrl_frame = ttk.LabelFrame(self.root, text="Controls")
        ctrl_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(ctrl_frame, text="Readings Count:").pack(side=tk.LEFT, padx=5)
        self.count_entry = ttk.Entry(ctrl_frame, width=10)
        self.count_entry.insert(0, "50")
        self.count_entry.pack(side=tk.LEFT, padx=5)

        self.start_btn = ttk.Button(
            ctrl_frame,
            text="1. Start Measurement",
            command=self.start_measurement,
            state=tk.DISABLED,
        )
        self.start_btn.pack(side=tk.LEFT, padx=10)

        self.fetch_btn = ttk.Button(
            ctrl_frame,
            text="2. Fetch & Plot Results",
            command=self.fetch_data,
            state=tk.DISABLED,
        )
        self.fetch_btn.pack(side=tk.LEFT, padx=10)

        ttk.Label(self.root, textvariable=self.status_var, foreground="blue").pack(pady=5)

        content = ttk.Frame(self.root)
        content.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        plot_frame = ttk.Frame(content)
        plot_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.figure, self.ax = plt.subplots(figsize=(5, 5), dpi=100)
        self.ax.set_title("Current Measurements")
        self.ax.set_xlabel("Sample Index")
        self.ax.set_ylabel("Current (A)")
        self.ax.grid(True)

        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        data_frame = ttk.LabelFrame(content, text="Raw Data Log")
        data_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))

        self.data_text = scrolledtext.ScrolledText(
            data_frame,
            width=25,
            height=20,
            state=tk.DISABLED,
            font=("Consolas", 10),
        )
        self.data_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def _ensure_rm(self) -> None:
        if self.rm is None:
            self.rm = pyvisa.ResourceManager()

    def connect(self) -> None:
        resource = self.visa_entry.get().strip()
        if not resource:
            messagebox.showerror("Connection", "Provide a VISA resource string.")
            return
        try:
            self._ensure_rm()
            assert self.rm is not None
            self.inst = self.rm.open_resource(resource)
            self.inst.timeout = 5000
            self.inst.read_termination = "\n"
            self.inst.write_termination = "\n"
            self.inst.clear()
            self.inst.write(TSP_SCRIPT.strip())
            self.inst.write("AmmeterFunctions()")
            self.status_var.set(f"Connected to {resource}. Functions loaded.")
            self.start_btn.configure(state=tk.NORMAL)
            self.fetch_btn.configure(state=tk.NORMAL)
            messagebox.showinfo("Connection", "Connected and script loaded successfully.")
        except Exception as exc:
            self.status_var.set("Connection Failed")
            messagebox.showerror("Connection", str(exc))

    def start_measurement(self) -> None:
        if not self.inst:
            return
        try:
            count = int(self.count_entry.get())
        except ValueError:
            messagebox.showerror("Input", "Count must be an integer.")
            return
        try:
            self.inst.write(f"StartAmmeterBurst({count})")
            self.status_var.set(f"Measurement of {count} points started...")
            self._expected_count = count
        except Exception as exc:
            messagebox.showerror("Start", str(exc))

    def fetch_data(self) -> None:
        if not self.inst:
            return
        if self._bg_thread and self._bg_thread.is_alive():
            return

        self._stop_event.clear()
        self.status_var.set("Fetching data...")
        self.fetch_btn.configure(state=tk.DISABLED)
        self.start_btn.configure(state=tk.DISABLED)

        def worker() -> None:
            try:
                currents = self._retrieve_currents()
            except Exception as exc:  # noqa: BLE001
                self.root.after(0, lambda e=exc: self._fetch_failed(e))
                return
            self.root.after(0, lambda data=currents: self._fetch_succeeded(data))

        self._bg_thread = threading.Thread(target=worker, daemon=True)
        self._bg_thread.start()

    def _retrieve_currents(self) -> list[float]:
        assert self.inst is not None
        self._wait_for_buffer_ready()
        self.inst.write("GetAmmeterData()")
        raw_content = ""
        started = False
        while True:
            if self._stop_event.is_set():
                raise RuntimeError("Fetch cancelled.")
            try:
                line = self.inst.read()
            except visa_errors.VisaIOError:
                break
            if "DataStart" in line:
                started = True
                continue
            if "DataEnd" in line:
                break
            if "Error" in line:
                raise RuntimeError(line.strip())
            if started:
                raw_content += line

        if not raw_content:
            raise RuntimeError("No data found between tags.")

        currents: list[float] = []
        for token in raw_content.replace("\n", ",").split(","):
            if self._stop_event.is_set():
                raise RuntimeError("Fetch cancelled.")
            token = token.strip()
            if not token:
                continue
            try:
                currents.append(float(token))
            except ValueError:
                continue

        if not currents:
            raise RuntimeError("Parsed 0 values from instrument output.")
        return currents

    def _wait_for_buffer_ready(self) -> None:
        assert self.inst is not None
        expected = self._expected_count or 0
        timeout = max(5.0, expected * 0.01 + 2.0)
        poll_interval = 0.1
        deadline = time.perf_counter() + timeout
        last_count = 0
        while time.perf_counter() < deadline:
            if self._stop_event.is_set():
                raise RuntimeError("Fetch cancelled.")
            
            response = self.inst.query("print(smua.nvbuffer1.n)").strip()
            
            try:
                last_count = int(float(response))
            except ValueError:
                last_count = 0
            
            if expected > 0:
                if last_count >= expected:
                    return
            elif last_count > 0:
                return
            time.sleep(poll_interval)
        
        raise RuntimeError(
            f"Buffer still empty (last count={last_count}). Did the measurement complete?"
        )

    def _fetch_failed(self, exc: Exception) -> None:
        self.status_var.set("Error fetching data")
        if not self._closing:
            messagebox.showerror("Fetch", f"Failed to fetch or parse data:\n{exc}")
        self._bg_thread = None
        self._restore_controls()

    def _fetch_succeeded(self, currents: list[float]) -> None:
        self._bg_thread = None
        if not self._closing:
            self._update_plot(currents)
            self._update_log(currents)
            self.status_var.set(f"Successfully plotted {len(currents)} points.")
        self._restore_controls()

    def _restore_controls(self) -> None:
        if self._closing:
            return
        state = tk.NORMAL if self.inst is not None else tk.DISABLED
        self.start_btn.configure(state=state)
        self.fetch_btn.configure(state=state)

    def _update_plot(self, currents: list[float]) -> None:
        self.ax.clear()
        self.ax.plot(currents, marker="o", linestyle="-", markersize=4)
        self.ax.set_title(f"Current Measurements (N={len(currents)})")
        self.ax.set_xlabel("Sample Index")
        self.ax.set_ylabel("Current (A)")
        
        # --- FIX: Force Scientific Notation on Y-Axis ---
        # scilimits=(0,0) forces scientific notation for all numbers.
        # This prevents the confusing "offset" notation where Matplotlib
        # puts "1e-9" at the top of the axis and labels ticks "0, 1, 2".
        self.ax.ticklabel_format(style='sci', axis='y', scilimits=(0,0))
        
        self.ax.grid(True)
        self.canvas.draw()

    def _update_log(self, currents: list[float]) -> None:
        self.data_text.configure(state=tk.NORMAL)
        self.data_text.delete("1.0", tk.END)
        for idx, value in enumerate(currents, start=1):
            self.data_text.insert(tk.END, f"{idx:03d}: {value:.6e} A\n")
        self.data_text.configure(state=tk.DISABLED)

    def _on_close(self) -> None:
        self._closing = True
        self._stop_event.set()
        if self._bg_thread and self._bg_thread.is_alive():
            self._bg_thread.join(timeout=2)
        if self.inst is not None:
            try:
                self.inst.close()
            except Exception:
                pass
        if self.rm is not None:
            try:
                self.rm.close()
            except Exception:
                pass
        self.root.quit()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    KeithleyAmmeterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()