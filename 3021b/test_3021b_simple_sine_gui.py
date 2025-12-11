import threading
import time
import tkinter as tk
from tkinter import scrolledtext

import pyvisa

DEFAULT_ADDR = "TCPIP0::169.254.6.24::inst0::INSTR"


class AFG3021BSineGui:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("AFG3021B Sine Setup")

        self.rm = None
        self.inst = None
        self.connected = False

        top = tk.Frame(root)
        top.pack(padx=10, pady=8, fill=tk.X)

        tk.Label(top, text="VISA Address:").grid(row=0, column=0, sticky="w")
        self.addr_var = tk.StringVar(value=DEFAULT_ADDR)
        tk.Entry(top, textvariable=self.addr_var, width=45).grid(row=0, column=1, sticky="we", columnspan=3)
        self.btn_connect = tk.Button(top, text="Connect", command=self.on_connect)
        self.btn_connect.grid(row=0, column=4, padx=(6, 0))
        self.btn_disconnect = tk.Button(top, text="Disconnect", command=self.on_disconnect, state="disabled")
        self.btn_disconnect.grid(row=0, column=5, padx=(6, 0))

        tk.Label(top, text="Frequency (Hz):").grid(row=1, column=0, sticky="w")
        self.freq_var = tk.StringVar(value="100000")
        tk.Entry(top, textvariable=self.freq_var, width=12).grid(row=1, column=1, sticky="w")

        tk.Label(top, text="Amplitude (Vpp):").grid(row=1, column=2, sticky="w")
        self.amp_var = tk.StringVar(value="1.0")
        tk.Entry(top, textvariable=self.amp_var, width=12).grid(row=1, column=3, sticky="w")

        tk.Label(top, text="Offset (V):").grid(row=1, column=4, sticky="w")
        self.offset_var = tk.StringVar(value="0.0")
        tk.Entry(top, textvariable=self.offset_var, width=10).grid(row=1, column=5, sticky="w")

        tk.Label(top, text="Load (ohms or INF):").grid(row=2, column=0, sticky="w")
        self.load_var = tk.StringVar(value="INF")
        tk.Entry(top, textvariable=self.load_var, width=12).grid(row=2, column=1, sticky="w")

        top.grid_columnconfigure(1, weight=1)
        top.grid_columnconfigure(3, weight=1)
        top.grid_columnconfigure(5, weight=1)

        btns = tk.Frame(root)
        btns.pack(padx=10, pady=(0, 6), fill=tk.X)
        tk.Button(btns, text="Apply Sine Setup", command=lambda: self.safe_run(self.apply_sine)).pack(side=tk.LEFT)
        tk.Button(btns, text="Output ON", command=lambda: self.safe_run(self.output_on)).pack(side=tk.LEFT, padx=6)
        tk.Button(btns, text="Output OFF", command=lambda: self.safe_run(self.output_off)).pack(side=tk.LEFT)
        tk.Button(btns, text="Query", command=lambda: self.safe_run(self.query_status)).pack(side=tk.LEFT, padx=6)
        tk.Button(btns, text="Errors", command=lambda: self.safe_run(self.drain_errors)).pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="Disconnected")
        tk.Label(root, textvariable=self.status_var, anchor="w").pack(padx=10, fill=tk.X)

        self.log = scrolledtext.ScrolledText(root, width=80, height=16, state="disabled")
        self.log.pack(padx=10, pady=(0, 10), fill=tk.BOTH, expand=True)

    def log_print(self, *args):
        text = " ".join(str(a) for a in args)
        self.log.configure(state="normal")
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)
        self.log.configure(state="disabled")

    def safe_run(self, func):
        thread = threading.Thread(target=self._safe_wrapper, args=(func,))
        thread.daemon = True
        thread.start()

    def _safe_wrapper(self, func):
        try:
            func()
        except Exception as exc:
            self.log_print("Error:", exc)

    def ensure_inst(self):
        if not self.inst:
            raise RuntimeError("Not connected.")

    def on_connect(self):
        addr = self.addr_var.get().strip()
        try:
            if self.rm is None:
                self.rm = pyvisa.ResourceManager()
            if self.inst:
                try:
                    self.inst.close()
                except Exception:
                    pass
            self.inst = self.rm.open_resource(addr)
            self.inst.timeout = 5000
            self.inst.read_termination = "\n"
            self.inst.write_termination = "\n"
            idn = self.inst.query("*IDN?").strip()
            self.log_print("Connected:", idn)
            self.inst.write("*CLS")
            self.inst.write("*RST")
            time.sleep(0.6)
            self.connected = True
            self.status_var.set(f"Connected: {idn}")
            self.btn_connect.configure(state="disabled")
            self.btn_disconnect.configure(state="normal")
        except Exception as exc:
            self.log_print("Connect error:", exc)

    def on_disconnect(self):
        try:
            if self.inst:
                try:
                    self.inst.write("OUTPut1:STATe OFF")
                except Exception:
                    pass
                try:
                    self.inst.close()
                except Exception:
                    pass
            self.inst = None
            self.connected = False
            self.status_var.set("Disconnected")
            self.btn_connect.configure(state="normal")
            self.btn_disconnect.configure(state="disabled")
            self.log_print("Disconnected.")
        finally:
            if self.rm:
                try:
                    self.rm.close()
                except Exception:
                    pass
                self.rm = None

    def apply_sine(self):
        self.ensure_inst()
        freq = float(self.freq_var.get())
        if freq <= 0:
            raise ValueError("Frequency must be > 0.")
        amp = float(self.amp_var.get())
        if amp <= 0:
            raise ValueError("Amplitude must be > 0.")
        offset = float(self.offset_var.get())

        load_text = self.load_var.get().strip().upper()

        self.inst.write("OUTPut1:STATe OFF")
        if load_text:
            if load_text in {"INF", "INFINITE", "HIGHZ"}:
                self.inst.write("OUTPut1:IMPedance INF")
            else:
                value = float(load_text)
                if value <= 0:
                    raise ValueError("Load must be > 0.")
                self.inst.write(f"OUTPut1:IMPedance {value}")
        self.inst.write("*CLS")
        self.inst.write("SOURce1:FUNCtion:SHAPe SIN")
        self.inst.write(f"SOURce1:FREQuency:FIXed {freq}")
        self.inst.write("SOURce1:VOLTage:UNIT VPP")
        self.inst.write(f"SOURce1:VOLTage:LEVel:IMMediate:AMPLitude {amp}")
        self.inst.write(f"SOURce1:VOLTage:LEVel:IMMediate:OFFSet {offset}")
        self.log_print(f"Sine applied: {freq} Hz, {amp} Vpp, offset {offset} V")

    def output_on(self):
        self.ensure_inst()
        self.inst.write("OUTPut1:STATe ON")
        self.log_print("Output ON")

    def output_off(self):
        self.ensure_inst()
        self.inst.write("OUTPut1:STATe OFF")
        self.log_print("Output OFF")

    def query_status(self):
        self.ensure_inst()
        shape = self.inst.query("SOURce1:FUNCtion:SHAPe?").strip()
        freq = self.inst.query("SOURce1:FREQuency:FIXed?").strip()
        amp = self.inst.query("SOURce1:VOLTage:LEVel:IMMediate:AMPLitude?").strip()
        offset = self.inst.query("SOURce1:VOLTage:LEVel:IMMediate:OFFSet?").strip()
        state = self.inst.query("OUTPut1:STATe?").strip()
        self.log_print(f"Shape: {shape}")
        self.log_print(f"Freq: {freq} Hz")
        self.log_print(f"Amp : {amp} Vpp")
        self.log_print(f"Offset: {offset} V")
        self.log_print(f"Output: {state}")

    def drain_errors(self):
        self.ensure_inst()
        for _ in range(6):
            err = self.inst.query("SYSTem:ERRor?").strip()
            self.log_print("ERR:", err)
            if err.startswith("0,"):
                break


def main():
    root = tk.Tk()
    gui = AFG3021BSineGui(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (gui.on_disconnect(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
