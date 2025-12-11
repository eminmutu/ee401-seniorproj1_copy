"""Simple SDG1020 pulse GUI using PyVISA.

Allows connecting over USB, configuring a pulse waveform (period, amplitude,
offset, duty cycle) and toggling the output of channel 1.
"""

import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext

import pyvisa


DEFAULT_ADDR = "USB0::0xF4ED::0xEE3A::NDG10GA1160419::INSTR"
CHANNEL = 1
ALL_CHANNELS = (1, 2)


class SDG1020PulseGui:
	def __init__(self, root: tk.Tk) -> None:
		self.root = root
		self.root.title("SDG1020 Pulse Control")

		self.rm = None
		self.inst = None

		root.columnconfigure(0, weight=1)
		root.rowconfigure(1, weight=1)

		top = tk.Frame(root, padx=12, pady=12)
		top.grid(row=0, column=0, sticky="nsew")
		for col in range(4):
			top.grid_columnconfigure(col, weight=1)

		tk.Label(top, text="VISA Address:").grid(row=0, column=0, sticky="w")
		self.addr_var = tk.StringVar(value=DEFAULT_ADDR)
		tk.Entry(top, textvariable=self.addr_var).grid(
			row=0, column=1, columnspan=2, sticky="ew"
		)
		tk.Button(top, text="List", command=self.safe_run(self.list_resources)).grid(
			row=0, column=3, sticky="ew", padx=(6, 0)
		)

		tk.Label(top, text="Period (s / SI)").grid(row=1, column=0, sticky="w", pady=(8, 0))
		self.period_var = tk.StringVar(value="1e-3")
		tk.Entry(top, textvariable=self.period_var).grid(
			row=1, column=1, sticky="ew", pady=(8, 0)
		)

		tk.Label(top, text="Amplitude (Vpp)").grid(row=1, column=2, sticky="w", pady=(8, 0))
		self.amp_var = tk.StringVar(value="2.0")
		tk.Entry(top, textvariable=self.amp_var).grid(
			row=1, column=3, sticky="ew", pady=(8, 0)
		)

		tk.Label(top, text="Pulse Width (s / SI)").grid(row=2, column=0, sticky="w", pady=(6, 0))
		self.width_var = tk.StringVar(value="5e-4")
		tk.Entry(top, textvariable=self.width_var).grid(
			row=2, column=1, sticky="ew", pady=(6, 0)
		)

		tk.Label(top, text="Offset (V)").grid(row=2, column=2, sticky="w", pady=(6, 0))
		self.offset_var = tk.StringVar(value="0.0")
		tk.Entry(top, textvariable=self.offset_var).grid(
			row=2, column=3, sticky="ew", pady=(6, 0)
		)

		btns = tk.Frame(root, padx=12)
		btns.grid(row=2, column=0, sticky="ew", pady=(6, 6))
		btns.columnconfigure(0, weight=1)
		btns.columnconfigure(1, weight=1)
		btns.columnconfigure(2, weight=1)
		btns.columnconfigure(3, weight=1)

		self.btn_connect = tk.Button(btns, text="Connect", command=self.safe_run(self.connect))
		self.btn_connect.grid(row=0, column=0, sticky="ew")

		self.btn_disconnect = tk.Button(
			btns, text="Disconnect", state="disabled", command=self.safe_run(self.disconnect)
		)
		self.btn_disconnect.grid(row=0, column=1, sticky="ew", padx=(6, 0))

		tk.Button(btns, text="Apply Pulse", command=self.safe_run(self.apply_pulse)).grid(
			row=0, column=2, sticky="ew", padx=(6, 0)
		)
		tk.Button(btns, text="Query", command=self.safe_run(self.query_waveform)).grid(
			row=0, column=3, sticky="ew", padx=(6, 0)
		)

		tk.Button(btns, text="Output ON", command=self.safe_run(self.output_on)).grid(
			row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0)
		)
		tk.Button(btns, text="Output OFF", command=self.safe_run(self.output_off)).grid(
			row=1, column=2, columnspan=2, sticky="ew", padx=(6, 0), pady=(6, 0)
		)

		self.status_var = tk.StringVar(value="Disconnected")
		tk.Label(root, textvariable=self.status_var, anchor="w", padx=12).grid(
			row=3, column=0, sticky="ew"
		)

		self.log = scrolledtext.ScrolledText(root, width=80, height=14, state="normal")
		self.log.grid(row=4, column=0, padx=12, pady=(0, 12), sticky="nsew")
		self.log.configure(state="disabled")

	# --- GUI helpers ---
	def safe_run(self, func):
		def _runner():
			try:
				func()
			except Exception as exc:
				self.log_message(f"Error: {exc}")
		return lambda: threading.Thread(target=_runner, daemon=True).start()

	def log_message(self, msg: str) -> None:
		self.log.configure(state="normal")
		self.log.insert(tk.END, msg + "\n")
		self.log.see(tk.END)
		self.log.configure(state="disabled")

	# --- VISA operations ---
	def list_resources(self):
		if self.rm is None:
			self.rm = pyvisa.ResourceManager()
		resources = self.rm.list_resources()
		msg = "Resources: " + (", ".join(resources) if resources else "<none>")
		self.log_message(msg)

	def connect(self):
		addr = self.addr_var.get().strip()
		if not addr:
			raise ValueError("VISA address cannot be empty")
		if self.rm is None:
			self.rm = pyvisa.ResourceManager()
		if self.inst is not None:
			self.inst.close()
			self.inst = None
		inst = self.rm.open_resource(addr)
		inst.timeout = 10000
		inst.read_termination = ""
		inst.write_termination = "\n"
		idn = inst.query("*IDN?").strip()
		self.inst = inst
		self.status_var.set(f"Connected: {addr}")
		self.btn_connect.config(state="disabled")
		self.btn_disconnect.config(state="normal")
		self.log_message(f"Connected: {idn}")

	def disconnect(self):
		if self.inst is not None:
			try:
				self._disable_outputs()
				self.inst.close()
			finally:
				self.inst = None
		self.status_var.set("Disconnected")
		self.btn_connect.config(state="normal")
		self.btn_disconnect.config(state="disabled")
		self.log_message("Disconnected from instrument")

	def _require_inst(self):
		if self.inst is None:
			raise RuntimeError("Instrument not connected")
		return self.inst

	def _disable_outputs(self) -> None:
		if self.inst is None:
			return
		for ch in ALL_CHANNELS:
			try:
				self.inst.write(f"C{ch}:OUTP OFF")
			except Exception:
				pass

	# --- Pulse configuration ---
	@staticmethod
	def _parse_time(value: str) -> float:
		val = value.strip().lower()
		if not val:
			raise ValueError("Period cannot be empty")
		suffixes = {
			"s": 1.0,
			"ms": 1e-3,
			"us": 1e-6,
			"µs": 1e-6,
			"ns": 1e-9,
			"ps": 1e-12,
		}
		for suf in sorted(suffixes, key=len, reverse=True):
			if val.endswith(suf):
				num = float(val[: -len(suf)])
				return num * suffixes[suf]
		return float(val)

	def apply_pulse(self):
		inst = self._require_inst()
		period = self._parse_time(self.period_var.get())
		if period <= 0:
			raise ValueError("Period must be positive")
		amplitude = float(self.amp_var.get())
		if amplitude <= 0:
			raise ValueError("Amplitude must be positive")
		width = self._parse_time(self.width_var.get())
		if width <= 0 or width >= period:
			raise ValueError("Pulse width must be positive and less than period")
		offset = float(self.offset_var.get())

		duty = (width / period) * 100.0
		cmd = (
			f"C{CHANNEL}:BSWV WVTP,PULSE,"
			f"PERI,{period:.9g},AMP,{amplitude:.9g},"
			f"OFST,{offset:.9g},DUTY,{duty:.9g}"
		)
		inst.write(cmd)
		self.status_var.set(
			f"Pulse set: T={period:.4g}s, Amp={amplitude:.4g}Vpp, Width={width:.4g}s, Offset={offset:.4g}V"
		)
		self.log_message(cmd)

	def output_on(self):
		inst = self._require_inst()
		inst.write(f"C{CHANNEL}:OUTP ON")
		self.status_var.set("Output ON")
		self.log_message("Output enabled")

	def output_off(self):
		inst = self._require_inst()
		inst.write(f"C{CHANNEL}:OUTP OFF")
		self.status_var.set("Output OFF")
		self.log_message("Output disabled")

	def query_waveform(self):
		inst = self._require_inst()
		resp = inst.query(f"C{CHANNEL}:BSWV?").strip()
		self.log_message(resp)


def main():
	root = tk.Tk()
	app = SDG1020PulseGui(root)

	def _on_close():
		try:
			app.disconnect()
		except Exception:
			pass
		root.destroy()

	root.protocol("WM_DELETE_WINDOW", _on_close)
	root.mainloop()


if __name__ == "__main__":
	main()

