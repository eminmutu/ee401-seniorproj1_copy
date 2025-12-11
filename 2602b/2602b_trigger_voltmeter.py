import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import pyvisa
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import re
import sys  # Added for clean exit

# -----------------------------------------------------------------------------
# THE LUA SCRIPT DEFINITION
# -----------------------------------------------------------------------------
TSP_SCRIPT = """
loadscript VoltmeterFunctions
    -- Constants for Trigger Modes
    local TRIG_RISINGA = digio.TRIG_RISINGA
    local DEFAULT_PULSEWIDTH = 10e-6

    function StartVoltmeterBurst(count, trig_line)
        -- Defaults
        if count == nil then count = 20 end
        if trig_line == nil then trig_line = 9 end

        smua.reset()
        
        -- --------------------------------------------------------
        -- 1. CONFIGURE DIGITAL TRIGGER (The "Start" Signal)
        -- --------------------------------------------------------
        -- Configure the specified line to detect a Rising Edge
        digio.trigger[trig_line].mode = TRIG_RISINGA
        digio.trigger[trig_line].pulsewidth = DEFAULT_PULSEWIDTH
        digio.trigger[trig_line].clear()

        -- --------------------------------------------------------
        -- 2. SPEED & RANGE OPTIMIZATION
        -- --------------------------------------------------------
        smua.measure.nplc = 0.001
        smua.measure.autozero = smua.AUTOZERO_OFF
        smua.measure.autorangev = smua.AUTORANGE_OFF
        smua.measure.rangev = 20
        smua.measure.delay = 0

        -- --------------------------------------------------------
        -- 3. VOLTMETER SOURCE CONFIGURATION
        -- --------------------------------------------------------
        smua.source.func = smua.OUTPUT_DCAMPS
        smua.source.rangei = 100e-9 
        smua.source.leveli = 0
        smua.source.limitv = 40 

        -- --------------------------------------------------------
        -- 4. BUFFER & TRIGGER MODEL SETUP
        -- --------------------------------------------------------
        smua.nvbuffer1.clear()
        smua.nvbuffer1.appendmode = 1
        smua.nvbuffer1.collecttimestamps = 1 
        smua.trigger.measure.v(smua.nvbuffer1)

        smua.trigger.count = count
        smua.trigger.source.action = smua.DISABLE
        smua.trigger.measure.action = smua.ENABLE
        
        -- HARDWARE LINK:
        -- The SMU Arm Layer will wait INDEFINITELY until the digital event occurs.
        -- This ensures < 10us latency between trigger and start of measurement.
        smua.trigger.arm.stimulus = digio.trigger[trig_line].EVENT_ID
        
        -- Source and Measure happen immediately after Arm is satisfied
        smua.trigger.source.stimulus = 0 
        smua.trigger.measure.stimulus = 0 

        -- --------------------------------------------------------
        -- 5. START EXECUTION
        -- --------------------------------------------------------
        print(string.format("Status: Armed. Waiting for Rising Edge on Digio %d...", trig_line))
        smua.source.output = smua.OUTPUT_ON
        
        -- Initiates the trigger model in the background. 
        -- The SMU is now "Armed" and waiting for the hardware signal.
        smua.trigger.initiate()
    end

    function GetVoltmeterData()
        smua.source.output = smua.OUTPUT_OFF
        if smua.nvbuffer1.n > 0 then
            print("DataStart")
            -- printbuffer output is comma delimited: 1.23e-5, 4.56e-5, ...
            printbuffer(1, smua.nvbuffer1.n, smua.nvbuffer1)
            print("DataEnd")
        else
            print("Error: Buffer is empty. (Trigger might not have occurred yet)")
        end
    end
endscript
"""

class KeithleyVoltmeterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Keithley 2602B Triggered Voltmeter")
        self.root.geometry("1000x700")
        
        self.inst = None
        self.rm = pyvisa.ResourceManager()
        
        # Handle Window Close Event Cleanly
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        
        self._setup_ui()

    def _setup_ui(self):
        # --- Connection Frame ---
        conn_frame = ttk.LabelFrame(self.root, text="Connection")
        conn_frame.pack(fill="x", padx=10, pady=5)
        
        ttk.Label(conn_frame, text="VISA Resource:").pack(side="left", padx=5)
        self.visa_entry = ttk.Entry(conn_frame, width=40)
        self.visa_entry.insert(0, "TCPIP0::169.254.0.1::5025::SOCKET") 
        self.visa_entry.pack(side="left", padx=5)
        
        self.connect_btn = ttk.Button(conn_frame, text="Connect & Load Script", command=self.connect_instrument)
        self.connect_btn.pack(side="left", padx=5)

        # --- Control Frame ---
        ctrl_frame = ttk.LabelFrame(self.root, text="Controls")
        ctrl_frame.pack(fill="x", padx=10, pady=5)
        
        # Readings Count Input
        ttk.Label(ctrl_frame, text="Readings Count:").pack(side="left", padx=5)
        self.count_entry = ttk.Entry(ctrl_frame, width=8)
        self.count_entry.insert(0, "50")
        self.count_entry.pack(side="left", padx=5)

        # Trigger Line Input
        ttk.Label(ctrl_frame, text="Trigger Line (Digio):").pack(side="left", padx=5)
        self.trig_entry = ttk.Entry(ctrl_frame, width=5)
        self.trig_entry.insert(0, "9")
        self.trig_entry.pack(side="left", padx=5)
        
        self.start_btn = ttk.Button(ctrl_frame, text="1. ARM Measurement", command=self.start_measurement, state="disabled")
        self.start_btn.pack(side="left", padx=10)
        
        self.fetch_btn = ttk.Button(ctrl_frame, text="2. Fetch Results", command=self.fetch_data, state="disabled")
        self.fetch_btn.pack(side="left", padx=10)

        # --- Status Label ---
        self.status_var = tk.StringVar(value="Not Connected")
        self.status_lbl = ttk.Label(self.root, textvariable=self.status_var, foreground="blue")
        self.status_lbl.pack(pady=5)

        # --- Main Content Area ---
        content_frame = ttk.Frame(self.root)
        content_frame.pack(fill="both", expand=True, padx=10, pady=5)

        # 1. Plotting Area (Left Side)
        plot_frame = ttk.Frame(content_frame)
        plot_frame.pack(side="left", fill="both", expand=True)
        
        self.figure, self.ax = plt.subplots(figsize=(5, 5), dpi=100)
        self.ax.set_title("Voltage Measurements")
        self.ax.set_xlabel("Sample Index")
        self.ax.set_ylabel("Voltage (V)")
        self.ax.grid(True)
        
        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # 2. Data Text Area (Right Side)
        data_frame = ttk.LabelFrame(content_frame, text="Raw Data Log")
        data_frame.pack(side="right", fill="y", padx=(10, 0))

        self.data_text = scrolledtext.ScrolledText(data_frame, width=28, height=20, state='disabled', font=("Consolas", 10))
        self.data_text.pack(fill="both", expand=True, padx=5, pady=5)

    def connect_instrument(self):
        resource = self.visa_entry.get()
        try:
            self.inst = self.rm.open_resource(resource)
            self.inst.timeout = 5000 
            self.inst.read_termination = '\n'
            self.inst.write_termination = '\n'
            
            self.inst.clear()
            # Send script (strip to avoid double newline warning)
            self.inst.write(TSP_SCRIPT.strip())
            # Execute script to define functions
            self.inst.write("VoltmeterFunctions()")
            
            self.status_var.set(f"Connected to {resource}. Functions Loaded.")
            self.start_btn.config(state="normal")
            self.fetch_btn.config(state="normal")
            messagebox.showinfo("Success", "Connected and script loaded successfully!")
            
        except Exception as e:
            self.status_var.set("Connection Failed")
            messagebox.showerror("Connection Error", str(e))

    def start_measurement(self):
        if not self.inst: return
        try:
            count = int(self.count_entry.get())
            trig_line = int(self.trig_entry.get())
            
            # Call Lua function with count and trigger line
            self.inst.write(f"StartVoltmeterBurst({count}, {trig_line})")
            
            self.status_var.set(f"Armed on Digio {trig_line}. Waiting for trigger to measure {count} points...")
            messagebox.showinfo("Armed", f"Instrument is ARMED on Digio {trig_line}.\n\nApply the trigger signal now.\n\nThen click 'Fetch Results' once done.")
            
        except ValueError:
            messagebox.showerror("Input Error", "Count and Trigger Line must be integers.")
        except Exception as e:
            messagebox.showerror("Communication Error", str(e))

    def fetch_data(self):
        if not self.inst: return
        
        try:
            self.status_var.set("Fetching data...")
            self.inst.write("GetVoltmeterData()")
            
            # Read until we find the start/end tags
            raw_content = ""
            started = False
            
            while True:
                try:
                    line = self.inst.read()
                    if "DataStart" in line:
                        started = True
                        continue 
                    if "DataEnd" in line:
                        break
                    if "Error" in line:
                        self.status_var.set(f"Instrument reported: {line.strip()}")
                        return
                    
                    if started:
                        raw_content += line
                except pyvisa.errors.VisaIOError:
                    break
            
            if not raw_content:
                self.status_var.set("No data found. Did you trigger the device?")
                return

            # --- PARSING ---
            voltages = []
            for item in raw_content.replace('\n', ',').split(','):
                item = item.strip()
                if item:
                    try:
                        voltages.append(float(item))
                    except ValueError:
                        pass 

            if not voltages:
                self.status_var.set("Parsed 0 values.")
                return

            # --- Update Plot ---
            self.ax.clear()
            self.ax.plot(voltages, marker='o', linestyle='-', markersize=4)
            self.ax.set_title(f"Voltage Measurements (N={len(voltages)})")
            self.ax.set_xlabel("Sample Index")
            self.ax.set_ylabel("Voltage (V)")
            self.ax.grid(True)
            self.canvas.draw()
            
            # --- Update Text Box ---
            self.data_text.config(state='normal')
            self.data_text.delete(1.0, tk.END)
            for i, val in enumerate(voltages):
                self.data_text.insert(tk.END, f"{i+1:03d}: {val:.6e} V\n")
            self.data_text.config(state='disabled')
            
            self.status_var.set(f"Successfully plotted {len(voltages)} points.")
            
        except Exception as e:
            self.status_var.set("Error fetching data")
            messagebox.showerror("Data Error", f"Failed to fetch or parse data:\n{e}")

    def _on_closing(self):
        """Clean up resources and force exit."""
        if self.inst:
            try:
                self.inst.close()
            except:
                pass
        self.root.quit()
        self.root.destroy()
        sys.exit(0)

if __name__ == "__main__":
    root = tk.Tk()
    app = KeithleyVoltmeterApp(root)
    root.mainloop()