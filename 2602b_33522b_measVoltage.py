from __future__ import annotations

import math
import sys
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import pyvisa
from pyvisa import errors as visa_errors


DEFAULT_KEYSIGHT_ADDRESS = "TCPIP0::169.254.5.22::5025::SOCKET"
DEFAULT_CH1_FREQ = "1000"
DEFAULT_CH1_WIDTH = "0.5e-3"
DEFAULT_CH1_AMPLITUDE = "2.0"
DEFAULT_CH1_OFFSET = "1.0"
DEFAULT_CH1_AMPLITUDE_UNIT = "Vpp"
DEFAULT_CH1_LOAD = "INF"
DEFAULT_CH1_PHASE = "0"
DEFAULT_CH1_LEAD = ""
DEFAULT_CH1_TRAIL = ""
DEFAULT_CH1_EDGE_MODE = "Both"
DEFAULT_CH1_MODE = "Burst"


TSP_SCRIPT = """
loadscript VoltmeterFunctions
	local TRIG_RISINGA = digio.TRIG_RISINGA
	local DEFAULT_PULSEWIDTH = 10e-6

	function StartVoltmeterBurst(count, trig_line)
		if count == nil then count = 20 end
		if trig_line == nil then trig_line = 9 end

		smua.reset()

		digio.trigger[trig_line].mode = TRIG_RISINGA
		digio.trigger[trig_line].pulsewidth = DEFAULT_PULSEWIDTH
		digio.trigger[trig_line].clear()

		smua.measure.nplc = 0.001
		smua.measure.autozero = smua.AUTOZERO_OFF
		smua.measure.autorangev = smua.AUTORANGE_OFF
		smua.measure.rangev = 20
		smua.measure.delay = 0

		smua.source.func = smua.OUTPUT_DCAMPS
		smua.source.rangei = 100e-9
		smua.source.leveli = 0
		smua.source.limitv = 40

		smua.nvbuffer1.clear()
		smua.nvbuffer1.appendmode = 1
		smua.nvbuffer1.collecttimestamps = 1
		smua.trigger.measure.v(smua.nvbuffer1)

		smua.trigger.count = count
		smua.trigger.source.action = smua.DISABLE
		smua.trigger.measure.action = smua.ENABLE
		smua.trigger.arm.stimulus = digio.trigger[trig_line].EVENT_ID
		smua.trigger.source.stimulus = 0
		smua.trigger.measure.stimulus = 0

		print(string.format("Status: Armed. Waiting for Rising Edge on Digio %d...", trig_line))
		smua.source.output = smua.OUTPUT_ON
		smua.trigger.initiate()
	end

	function GetVoltmeterData()
		smua.source.output = smua.OUTPUT_OFF
		if smua.nvbuffer1.n > 0 then
			print("DataStart")
			printbuffer(1, smua.nvbuffer1.n, smua.nvbuffer1)
			print("DataEnd")
		else
			print("Error: Buffer is empty. (Trigger might not have occurred yet)")
		end
	end
endscript
"""


class KeithleyVoltmeterPanel:
	"""Tkinter panel that controls the 2602B triggered voltmeter functions."""

	def __init__(self, parent: tk.Misc) -> None:
		self.parent = parent
		self.frame = ttk.Frame(parent, padding=10)
		self.frame.pack(fill=tk.BOTH, expand=True)

		self.rm: pyvisa.ResourceManager | None = None
		self.inst: pyvisa.resources.MessageBasedResource | None = None

		self.status_var = tk.StringVar(master=self.frame, value="Not Connected")

		self._build_ui()

	def _build_ui(self) -> None:
		conn_frame = ttk.LabelFrame(self.frame, text="Keithley Connection")
		conn_frame.pack(fill=tk.X, padx=5, pady=5)

		ttk.Label(conn_frame, text="VISA Resource:").pack(side=tk.LEFT, padx=4)
		self.visa_entry = ttk.Entry(conn_frame, width=40)
		self.visa_entry.insert(0, "TCPIP0::169.254.0.1::5025::SOCKET")
		self.visa_entry.pack(side=tk.LEFT, padx=4)
		ttk.Button(conn_frame, text="Connect & Load Script", command=self.connect_instrument).pack(
			side=tk.LEFT, padx=4
		)

		ctrl_frame = ttk.LabelFrame(self.frame, text="Keithley Controls")
		ctrl_frame.pack(fill=tk.X, padx=5, pady=5)

		ttk.Label(ctrl_frame, text="Readings Count:").pack(side=tk.LEFT, padx=4)
		self.count_entry = ttk.Entry(ctrl_frame, width=8)
		self.count_entry.insert(0, "50")
		self.count_entry.pack(side=tk.LEFT)

		ttk.Label(ctrl_frame, text="Trigger Line:").pack(side=tk.LEFT, padx=4)
		self.trig_entry = ttk.Entry(ctrl_frame, width=5)
		self.trig_entry.insert(0, "9")
		self.trig_entry.pack(side=tk.LEFT)

		self.start_btn = ttk.Button(
			ctrl_frame, text="1. Arm Measurement", command=self.start_measurement, state="disabled"
		)
		self.start_btn.pack(side=tk.LEFT, padx=10)

		self.fetch_btn = ttk.Button(
			ctrl_frame, text="2. Fetch Results", command=self.fetch_data, state="disabled"
		)
		self.fetch_btn.pack(side=tk.LEFT, padx=4)

		ttk.Label(self.frame, textvariable=self.status_var, foreground="blue").pack(pady=(0, 6))

		content = ttk.Frame(self.frame)
		content.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

		plot_frame = ttk.Frame(content)
		plot_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

		self.figure = plt.Figure(figsize=(5, 5), dpi=100)
		self.ax = self.figure.add_subplot(111)
		self.ax.set_title("Voltage Measurements")
		self.ax.set_xlabel("Sample Index")
		self.ax.set_ylabel("Voltage (V)")
		self.ax.grid(True)
		self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
		self.canvas.draw()
		self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

		data_frame = ttk.LabelFrame(content, text="Raw Data Log")
		data_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
		self.data_text = scrolledtext.ScrolledText(
			data_frame, width=28, height=20, state=tk.DISABLED, font=("Consolas", 10)
		)
		self.data_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

	def _ensure_rm(self) -> None:
		if self.rm is None:
			self.rm = pyvisa.ResourceManager()

	def connect_instrument(self) -> None:
		resource = self.visa_entry.get().strip()
		if not resource:
			messagebox.showerror("Keithley", "Provide a VISA resource string.")
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
			self.inst.write("VoltmeterFunctions()")
			self.status_var.set(f"Connected to {resource}. Functions loaded.")
			self.start_btn.configure(state=tk.NORMAL)
			self.fetch_btn.configure(state=tk.NORMAL)
			messagebox.showinfo("Keithley", "Connected and script loaded successfully.")
		except Exception as exc:
			self.status_var.set("Connection Failed")
			messagebox.showerror("Keithley", str(exc))

	def start_measurement(self) -> None:
		if not self.inst:
			return
		try:
			count = int(self.count_entry.get())
			trig_line = int(self.trig_entry.get())
		except ValueError:
			messagebox.showerror("Keithley", "Count and trigger line must be integers.")
			return

		try:
			self.inst.write(f"StartVoltmeterBurst({count}, {trig_line})")
			self.status_var.set(
				f"Armed on Digio {trig_line}. Waiting for trigger to capture {count} readings..."
			)
			messagebox.showinfo(
				"Keithley",
				f"Instrument armed on Digio {trig_line}.\nTrigger the SMU, then click 'Fetch Results'.",
			)
		except Exception as exc:
			messagebox.showerror("Keithley", str(exc))

	def fetch_data(self) -> None:
		if not self.inst:
			return
		try:
			self.status_var.set("Fetching data...")
			self.inst.write("GetVoltmeterData()")
			raw_content = ""
			started = False
			while True:
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
					self.status_var.set(line.strip())
					return
				if started:
					raw_content += line

			if not raw_content:
				self.status_var.set("No data received. Did the trigger fire?")
				return

			voltages: list[float] = []
			for token in raw_content.replace("\n", ",").split(","):
				token = token.strip()
				if not token:
					continue
				try:
					voltages.append(float(token))
				except ValueError:
					continue

			if not voltages:
				self.status_var.set("Parsed 0 values from instrument output.")
				return

			self._update_plot(voltages)
			self._update_log(voltages)
			self.status_var.set(f"Successfully plotted {len(voltages)} points.")
		except Exception as exc:
			self.status_var.set("Error fetching data")
			messagebox.showerror("Keithley", f"Failed to fetch or parse data:\n{exc}")

	def _update_plot(self, voltages: list[float]) -> None:
		self.ax.clear()
		self.ax.plot(voltages, marker="o", linestyle="-", markersize=4)
		self.ax.set_title(f"Voltage Measurements (N={len(voltages)})")
		self.ax.set_xlabel("Sample Index")
		self.ax.set_ylabel("Voltage (V)")
		self.ax.grid(True)
		self.canvas.draw()

	def _update_log(self, voltages: list[float]) -> None:
		self.data_text.configure(state=tk.NORMAL)
		self.data_text.delete("1.0", tk.END)
		for idx, value in enumerate(voltages, start=1):
			self.data_text.insert(tk.END, f"{idx:03d}: {value:.6e} V\n")
		self.data_text.configure(state=tk.DISABLED)

	def shutdown(self) -> None:
		if self.inst is not None:
			try:
				self.inst.close()
			except Exception:
				pass
		self.inst = None
		if self.rm is not None:
			try:
				self.rm.close()
			except Exception:
				pass
		self.rm = None
		self.start_btn.configure(state=tk.DISABLED)
		self.fetch_btn.configure(state=tk.DISABLED)
		self.status_var.set("Disconnected")


class KeysightPulsePanel:
	"""Encapsulates the channel 2 burst controls plus channel 1 sync helper."""

	def __init__(self, parent: tk.Misc) -> None:
		self.parent = parent
		self.rm: pyvisa.ResourceManager | None = None
		self.inst: pyvisa.resources.MessageBasedResource | None = None
		self.connected = False
		self.configured = False
		self.output_on = False
		self.ch1_output_on = False
		self.ch1_configured = False
		self.ch1_is_burst = True

		self.addr_var = tk.StringVar(value=DEFAULT_KEYSIGHT_ADDRESS)
		self.freq_var = tk.StringVar(value="1000")
		self.vpp_var = tk.StringVar(value="4.2")
		self.cycles_var = tk.StringVar(value="1")
		self.settle_var = tk.StringVar(value="1.2")
		self.phase_delay_var = tk.StringVar(value="1e-6")
		self.pulse_hint_var = tk.StringVar()
		self.ch1_freq_var = tk.StringVar(value=DEFAULT_CH1_FREQ)
		self.ch1_width_var = tk.StringVar(value=DEFAULT_CH1_WIDTH)
		self.ch1_amp_var = tk.StringVar(value=DEFAULT_CH1_AMPLITUDE)
		self.ch1_offset_var = tk.StringVar(value=DEFAULT_CH1_OFFSET)
		self.ch1_amp_unit_var = tk.StringVar(value=DEFAULT_CH1_AMPLITUDE_UNIT)
		self.ch1_load_var = tk.StringVar(value=DEFAULT_CH1_LOAD)
		self.ch1_phase_var = tk.StringVar(value=DEFAULT_CH1_PHASE)
		self.ch1_lead_var = tk.StringVar(value=DEFAULT_CH1_LEAD)
		self.ch1_trail_var = tk.StringVar(value=DEFAULT_CH1_TRAIL)
		self.ch1_edge_mode_var = tk.StringVar(value=DEFAULT_CH1_EDGE_MODE)
		self.ch1_period_hint_var = tk.StringVar(value="Period: --")
		self.ch1_burst_var = tk.StringVar(value="1")
		self.ch1_mode_var = tk.StringVar(value=DEFAULT_CH1_MODE)

		self._build_ui(parent)
		try:
			self.freq_var.trace_add("write", lambda *_: self._update_hint())
		except AttributeError:
			self.freq_var.trace("w", lambda *_: self._update_hint())
		self._update_hint()
		try:
			self.ch1_freq_var.trace_add("write", lambda *_: self._update_ch1_period_hint())
		except AttributeError:
			self.ch1_freq_var.trace("w", lambda *_: self._update_ch1_period_hint())
		self._update_ch1_period_hint()
		try:
			self.ch1_mode_var.trace_add("write", lambda *_: self._update_ch1_mode_state())
		except AttributeError:
			self.ch1_mode_var.trace("w", lambda *_: self._update_ch1_mode_state())
		self._update_ch1_mode_state()

	def _build_ui(self, frame: tk.Misc) -> None:
		container = ttk.Frame(frame, padding=10)
		container.pack(fill=tk.BOTH, expand=True)
		container.columnconfigure(1, weight=1)

		ttk.Label(container, text="VISA address:").grid(column=0, row=0, sticky="w")
		ttk.Entry(container, textvariable=self.addr_var, width=32).grid(column=1, row=0, sticky="we", padx=(4, 8))
		btns = ttk.Frame(container)
		btns.grid(column=0, row=1, columnspan=2, sticky="w", pady=(6, 0))
		self.btn_connect = ttk.Button(btns, text="Connect", command=self.connect)
		self.btn_connect.pack(side=tk.LEFT)
		self.btn_disconnect = ttk.Button(btns, text="Disconnect", command=self.disconnect, state="disabled")
		self.btn_disconnect.pack(side=tk.LEFT, padx=6)

		cfg = ttk.LabelFrame(container, text="Channel 2 Pulse Settings")
		cfg.grid(column=0, row=2, columnspan=2, sticky="ew", pady=(10, 0))
		for col in range(4):
			cfg.columnconfigure(col, weight=1)

		ttk.Label(cfg, text="Frequency (Hz)").grid(column=0, row=0, sticky="e")
		ttk.Entry(cfg, textvariable=self.freq_var, width=12).grid(column=1, row=0, sticky="w")
		ttk.Label(cfg, textvariable=self.pulse_hint_var).grid(column=2, row=0, columnspan=2, sticky="w")

		ttk.Label(cfg, text="Amplitude (Vpp)").grid(column=0, row=1, sticky="e")
		ttk.Entry(cfg, textvariable=self.vpp_var, width=12).grid(column=1, row=1, sticky="w")
		ttk.Label(cfg, text="Burst cycles").grid(column=2, row=1, sticky="e")
		ttk.Entry(cfg, textvariable=self.cycles_var, width=8).grid(column=3, row=1, sticky="w")

		ttk.Label(cfg, text="Settle factor").grid(column=0, row=2, sticky="e")
		ttk.Entry(cfg, textvariable=self.settle_var, width=12).grid(column=1, row=2, sticky="w")
		ttk.Label(cfg, text="Phase delay (s, blank = dwell)").grid(column=2, row=2, sticky="e")
		ttk.Entry(cfg, textvariable=self.phase_delay_var, width=14).grid(column=3, row=2, sticky="w")

		action_row = ttk.Frame(container)
		action_row.grid(column=0, row=3, columnspan=2, pady=(10, 0), sticky="we")
		for i in range(4):
			action_row.columnconfigure(i, weight=1)
		self.btn_configure = ttk.Button(action_row, text="Configure", command=self.configure, state="disabled")
		self.btn_configure.grid(column=0, row=0, padx=4)
		self.btn_fire = ttk.Button(action_row, text="Send Pulse", command=self.fire_pulse, state="disabled")
		self.btn_fire.grid(column=1, row=0, padx=4)
		self.btn_stop = ttk.Button(action_row, text="Stop Output", command=self.stop, state="disabled")
		self.btn_stop.grid(column=2, row=0, padx=4)
		self.btn_toggle = ttk.Button(action_row, text="Ch2 Output OFF", command=self.toggle_output, state="disabled")
		self.btn_toggle.grid(column=3, row=0, padx=4)

		ch1_frame = ttk.LabelFrame(container, text="Channel 1 Pulse Settings")
		ch1_frame.grid(column=0, row=4, columnspan=2, sticky="ew", pady=(10, 0))
		for col in range(6):
			ch1_frame.columnconfigure(col, weight=1)

		ttk.Label(ch1_frame, text="Frequency (Hz)").grid(column=0, row=0, sticky="e")
		freq_wrap = ttk.Frame(ch1_frame)
		freq_wrap.grid(column=1, row=0, sticky="w")
		ttk.Entry(freq_wrap, textvariable=self.ch1_freq_var, width=12).pack(side=tk.LEFT)
		ttk.Label(freq_wrap, textvariable=self.ch1_period_hint_var).pack(side=tk.LEFT, padx=(6, 0))

		ttk.Label(ch1_frame, text="Pulse width (s or SI)").grid(column=2, row=0, sticky="e")
		ttk.Entry(ch1_frame, textvariable=self.ch1_width_var, width=14).grid(column=3, row=0, sticky="w")

		ttk.Label(ch1_frame, text="Burst count").grid(column=4, row=0, sticky="e")
		self.ch1_burst_entry = ttk.Entry(ch1_frame, textvariable=self.ch1_burst_var, width=8)
		self.ch1_burst_entry.grid(column=5, row=0, sticky="w")

		ttk.Label(ch1_frame, text="Mode").grid(column=4, row=1, sticky="e")
		mode_combo = ttk.Combobox(
			ch1_frame,
			textvariable=self.ch1_mode_var,
			values=("Burst", "Continuous"),
			state="readonly",
			width=10,
		)
		mode_combo.grid(column=5, row=1, sticky="w")

		ttk.Label(ch1_frame, text="Amplitude").grid(column=0, row=1, sticky="e")
		amp_frame = ttk.Frame(ch1_frame)
		amp_frame.grid(column=1, row=1, sticky="w")
		ttk.Entry(amp_frame, textvariable=self.ch1_amp_var, width=10).pack(side=tk.LEFT)
		amp_unit_combo = ttk.Combobox(
			amp_frame,
			textvariable=self.ch1_amp_unit_var,
			values=("Vpp", "Vrms"),
			state="readonly",
			width=6,
		)
		amp_unit_combo.pack(side=tk.LEFT, padx=(6, 0))

		ttk.Label(ch1_frame, text="Offset (V)").grid(column=2, row=1, sticky="e")
		ttk.Entry(ch1_frame, textvariable=self.ch1_offset_var, width=12).grid(column=3, row=1, sticky="w")

		ttk.Label(ch1_frame, text="Load (Ohm or INF)").grid(column=0, row=2, sticky="e")
		ttk.Entry(ch1_frame, textvariable=self.ch1_load_var, width=12).grid(column=1, row=2, sticky="w")
		ttk.Label(ch1_frame, text="Phase (deg)").grid(column=2, row=2, sticky="e")
		ttk.Entry(ch1_frame, textvariable=self.ch1_phase_var, width=12).grid(column=3, row=2, sticky="w")

		ttk.Label(ch1_frame, text="Lead edge (s)").grid(column=0, row=3, sticky="e")
		ttk.Entry(ch1_frame, textvariable=self.ch1_lead_var, width=12).grid(column=1, row=3, sticky="w")
		ttk.Label(ch1_frame, text="Trail edge (s)").grid(column=2, row=3, sticky="e")
		ttk.Entry(ch1_frame, textvariable=self.ch1_trail_var, width=12).grid(column=3, row=3, sticky="w")
		ttk.Label(ch1_frame, text="Edge mode").grid(column=4, row=3, sticky="e")
		edge_combo = ttk.Combobox(
			ch1_frame,
			textvariable=self.ch1_edge_mode_var,
			values=("Both", "Separate"),
			state="readonly",
			width=10,
		)
		edge_combo.grid(column=5, row=3, sticky="w")

		ch1_btns = ttk.Frame(ch1_frame)
		ch1_btns.grid(column=0, row=4, columnspan=6, sticky="w", pady=(6, 0))
		self.btn_ch1_configure = ttk.Button(
			ch1_btns,
			text="Apply Channel 1",
			command=self.configure_ch1,
			state="disabled",
		)
		self.btn_ch1_configure.pack(side=tk.LEFT)
		self.btn_ch1_toggle = ttk.Button(
			ch1_btns,
			text="Ch1 Output OFF",
			command=self.toggle_ch1_output,
			state="disabled",
		)
		self.btn_ch1_toggle.pack(side=tk.LEFT, padx=6)
		self.btn_ch1_query = ttk.Button(
			ch1_btns,
			text="Query Ch1",
			command=self.query_ch1_status,
			state="disabled",
		)
		self.btn_ch1_query.pack(side=tk.LEFT)

		self.log = scrolledtext.ScrolledText(container, height=14, state=tk.DISABLED)
		self.log.grid(column=0, row=5, columnspan=2, sticky="nsew", pady=(10, 0))
		container.rowconfigure(5, weight=1)

	def _log(self, *parts: object) -> None:
		msg = " ".join(str(p) for p in parts)
		self.log.configure(state=tk.NORMAL)
		self.log.insert(tk.END, msg + "\n")
		self.log.see(tk.END)
		self.log.configure(state=tk.DISABLED)

	def _update_hint(self) -> None:
		txt = self.freq_var.get().strip()
		try:
			freq = float(txt)
		except ValueError:
			self.pulse_hint_var.set("")
			return
		if freq <= 0:
			self.pulse_hint_var.set("")
			return
		period = 1.0 / freq
		self.pulse_hint_var.set(f"Period ~ {period*1e3:.3f} ms")

	def _update_ch1_period_hint(self) -> None:
		txt = self.ch1_freq_var.get().strip()
		if not txt:
			self.ch1_period_hint_var.set("Period: --")
			return
		try:
			freq = float(txt)
		except ValueError:
			self.ch1_period_hint_var.set("Period: --")
			return
		if freq <= 0:
			self.ch1_period_hint_var.set("Period: --")
			return
		period = 1.0 / freq
		self.ch1_period_hint_var.set(f"Period ~ {self._format_seconds_si(period)}")

	def _update_ch1_mode_state(self, *_: object) -> None:
		mode = (self.ch1_mode_var.get() or "Burst").strip().lower()
		state = tk.DISABLED if mode == "continuous" else tk.NORMAL
		if hasattr(self, "ch1_burst_entry"):
			self.ch1_burst_entry.configure(state=state)

	@staticmethod
	def _format_seconds_si(seconds: float) -> str:
		value = float(seconds)
		if value <= 0 or not math.isfinite(value):
			return "--"
		if value >= 1:
			return f"{value:g} s"
		if value >= 1e-3:
			return f"{value*1e3:g} ms"
		if value >= 1e-6:
			return f"{value*1e6:g} us"
		if value >= 1e-9:
			return f"{value*1e9:g} ns"
		return f"{value*1e12:g} ps"

	@staticmethod
	def _parse_time_to_seconds(text: str, *, field_name: str) -> float:
		raw = text.strip().lower().replace(" ", "")
		if not raw:
			raise ValueError(f"{field_name} is required.")
		units = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "ns": 1e-9, "ps": 1e-12}
		for suffix in sorted(units, key=len, reverse=True):
			if raw.endswith(suffix):
				number = float(raw[: -len(suffix)])
				return number * units[suffix]
		return float(raw)

	@staticmethod
	def _parse_float(text: str, *, field_name: str) -> float:
		try:
			return float(text.strip())
		except ValueError as exc:
			raise ValueError(f"{field_name} must be numeric.") from exc

	@classmethod
	def _parse_positive(cls, text: str, *, field_name: str) -> float:
		value = cls._parse_float(text, field_name=field_name)
		if value <= 0:
			raise ValueError(f"{field_name} must be > 0.")
		return value

	@staticmethod
	def _parse_int(text: str, *, field_name: str) -> int:
		try:
			value = int(float(text.strip()))
		except ValueError as exc:
			raise ValueError(f"{field_name} must be an integer.") from exc
		if value <= 0:
			raise ValueError(f"{field_name} must be > 0.")
		return value

	def _set_ch1_load(self, load_text: str) -> None:
		if not self.inst:
			raise RuntimeError("Instrument not connected.")
		load = load_text.strip().upper()
		if load in {"INF", "INFINITE", "HIGHZ", "HZ"}:
			self.inst.write(":OUTP1:LOAD INF")
			return
		try:
			value = float(load)
		except ValueError as exc:
			raise ValueError("Channel 1 load must be INF or numeric.") from exc
		if value <= 0:
			raise ValueError("Channel 1 load must be greater than 0 Ohm.")
		self.inst.write(f":OUTP1:LOAD {value}")

	def _update_ch1_button_label(self) -> None:
		label = "Ch1 Output ON" if self.ch1_output_on else "Ch1 Output OFF"
		self.btn_ch1_toggle.configure(text=label)

	def _ensure_ch1_output_on(self) -> None:
		if not self.inst or not self.ch1_configured:
			return
		self.inst.write(":OUTP1 ON")
		self.inst.write(":INIT1:IMM")
		if not self.ch1_output_on:
			self.ch1_output_on = True
		self._update_ch1_button_label()
		msg = (
			"Channel 1 armed and awaiting BUS trigger."
			if self.ch1_is_burst
			else "Channel 1 output enabled (continuous mode)."
		)
		self._log(msg)

	def start_ch1_for_trigger(self) -> None:
		if not self.inst or not self.connected:
			raise RuntimeError("Connect the Keysight 33522B first.")
		if not self.ch1_configured:
			raise RuntimeError("Configure Channel 1 before arming the trigger.")
		if not self.ch1_is_burst:
			self._log("Channel 1 continuous mode active; trigger arming not required.")
			return
		self.inst.write(":OUTP1 ON")
		self.ch1_output_on = True
		self._update_ch1_button_label()
		self._log("Channel 1 output forced ON for trigger synchronisation.")

	def force_ch1_off(self) -> None:
		if not self.inst:
			return
		try:
			self.inst.write(":OUTP1 OFF")
		except Exception:
			pass
		was_on = self.ch1_output_on
		self.ch1_output_on = False
		self._update_ch1_button_label()
		if was_on:
			self._log("Channel 1 output forced OFF after measurement.")

	def shutdown_outputs(self) -> None:
		if not self.inst:
			return
		try:
			self.inst.write(":OUTP2 OFF")
		except Exception:
			pass
		self.force_ch1_off()
		self.output_on = False
		self.ch1_output_on = False
		self.btn_toggle.configure(text="Ch2 Output OFF")
		self.btn_ch1_toggle.configure(text="Ch1 Output OFF")

	def connect(self) -> None:
		if self.connected:
			return
		addr = self.addr_var.get().strip()
		if not addr:
			messagebox.showerror("Keysight", "Provide a VISA address.")
			return
		try:
			if self.rm is None:
				self.rm = pyvisa.ResourceManager()
			self.inst = self.rm.open_resource(addr, timeout=5000)
			self.inst.write_termination = "\n"
			self.inst.read_termination = "\n"
			idn = self.inst.query("*IDN?").strip()
			self._log("Connected:", idn)
			self.connected = True
			self.btn_connect.configure(state=tk.DISABLED)
			self.btn_disconnect.configure(state=tk.NORMAL)
			self.btn_configure.configure(state=tk.NORMAL)
			self.btn_ch1_configure.configure(state=tk.NORMAL)
			self.btn_ch1_query.configure(state=tk.NORMAL)
			self.btn_ch1_toggle.configure(state=tk.DISABLED)
		except Exception as exc:
			self._log("Connect failed:", exc)
			messagebox.showerror("Keysight", str(exc))

	def disconnect(self) -> None:
		if not self.connected:
			return
		try:
			self.stop()
		except Exception:
			pass
		try:
			self.shutdown_outputs()
		except Exception:
			pass
		if self.inst:
			try:
				self.inst.close()
			except Exception:
				pass
		self.inst = None
		if self.rm:
			try:
				self.rm.close()
			except Exception:
				pass
		self.rm = None
		self.connected = False
		self.configured = False
		self.output_on = False
		self.ch1_output_on = False
		self.ch1_configured = False
		self.btn_connect.configure(state=tk.NORMAL)
		self.btn_disconnect.configure(state=tk.DISABLED)
		self.btn_configure.configure(state=tk.DISABLED)
		self.btn_fire.configure(state=tk.DISABLED)
		self.btn_stop.configure(state=tk.DISABLED)
		self.btn_toggle.configure(state=tk.DISABLED, text="Ch2 Output OFF")
		self.btn_ch1_configure.configure(state=tk.DISABLED)
		self.btn_ch1_toggle.configure(state=tk.DISABLED, text="Ch1 Output OFF")
		self.btn_ch1_query.configure(state=tk.DISABLED)
		self._log("Disconnected.")

	def configure(self) -> None:
		if not self.connected or not self.inst:
			messagebox.showwarning("Keysight", "Connect first.")
			return
		try:
			freq = float(self.freq_var.get())
			vpp = float(self.vpp_var.get())
			cycles = int(float(self.cycles_var.get()))
			settle = float(self.settle_var.get())
		except ValueError:
			messagebox.showerror("Keysight", "Enter numeric settings.")
			return
		if freq <= 0 or vpp <= 0 or cycles <= 0 or settle <= 0:
			messagebox.showerror("Keysight", "Values must be positive.")
			return
		if vpp > 10:
			messagebox.showerror("Keysight", "Amplitude limited to 10 Vpp.")
			return
		try:
			self.inst.write("*CLS")
			self.inst.write(":SOUR2:FUNC SQU")
			self.inst.write(f":SOUR2:FREQ {freq}")
			self.inst.write(":SOUR2:VOLT:LOW 0")
			self.inst.write(f":SOUR2:VOLT:HIGH {vpp}")
			self.inst.write(f":SOUR2:VOLT:OFFS {vpp/2.0}")
			self.inst.write(":SOUR2:PULS:DCYC 50")
			self.inst.write(":OUTP2:LOAD INF")
			self.inst.write(":SOUR2:BURSt:STAT ON")
			self.inst.write(":SOUR2:BURSt:MODE TRIG")
			self.inst.write(f":SOUR2:BURSt:NCYC {cycles}")
			self.inst.write(":TRIG2:SOUR BUS")
			self.inst.write(":INIT2:CONT OFF")
			self.inst.write(":OUTP2 ON")
			self.output_on = True
			self.btn_toggle.configure(text="Ch2 Output ON")
			self.configured = True
			self.output_on = False
			self.btn_fire.configure(state=tk.NORMAL)
			self.btn_stop.configure(state=tk.NORMAL)
			self.btn_toggle.configure(state=tk.NORMAL, text="Ch2 Output OFF")
			self._log(f"Ch2 configured: {freq} Hz, {vpp} Vpp, {cycles} cycle(s) per bus trigger.")
			auto_ok = self.configure_ch1(silent=True)
			if auto_ok:
				try:
					self._ensure_ch1_output_on()
				except Exception:
					pass
				self._log("Channel 1 auto-configured and output ON.")
		except Exception as exc:
			self._log("Configure failed:", exc)
			messagebox.showerror("Keysight", str(exc))

	def configure_ch1(self, *, silent: bool = False) -> bool:
		if not self.connected or not self.inst:
			if not silent:
				messagebox.showwarning("Channel 1", "Connect first.")
			return False
		try:
			freq = self._parse_positive(self.ch1_freq_var.get(), field_name="Channel 1 frequency")
			width = self._parse_time_to_seconds(self.ch1_width_var.get(), field_name="Pulse width")
			amplitude = self._parse_positive(self.ch1_amp_var.get(), field_name="Amplitude")
			offset = self._parse_float(self.ch1_offset_var.get(), field_name="Offset")
			load_text = self.ch1_load_var.get()
			phase = self._parse_float(self.ch1_phase_var.get(), field_name="Phase")
			lead_txt = self.ch1_lead_var.get().strip()
			trail_txt = self.ch1_trail_var.get().strip()
			edge_mode = self.ch1_edge_mode_var.get().strip().lower() or "both"
			mode = self.ch1_mode_var.get().strip().lower() or "burst"
			amp_unit = self.ch1_amp_unit_var.get().strip().upper() or "VPP"
			if amp_unit not in {"VPP", "VRMS"}:
				amp_unit = "VPP"

			period = 1.0 / freq
			if not (0 < width < period):
				raise ValueError("Pulse width must be greater than 0 and less than the period.")
			is_burst = mode != "continuous"

			try:
				burst_count = int(float(self.ch1_burst_var.get())) if is_burst else 0
			except ValueError:
				burst_count = 1 if is_burst else 0
			if is_burst and burst_count < 1:
				burst_count = 1

			self.inst.write(":OUTP1 OFF")
			self._set_ch1_load(load_text)
			self.inst.write(":SOUR1:FUNC PULS")
			self.inst.write(f":SOUR1:PULS:PER {period}")
			self.inst.write(f":SOUR1:PULS:WIDTh {width}")
			self.inst.write(f":SOUR1:VOLT:UNIT {amp_unit}")
			self.inst.write(f":SOUR1:VOLT:LEV:IMM:AMPL {amplitude}")
			self.inst.write(f":SOUR1:VOLT:OFFS {offset}")
			self.inst.write(f":SOUR1:PHAS {phase}")

			if edge_mode == "separate":
				if lead_txt:
					lead_val = self._parse_time_to_seconds(lead_txt, field_name="Lead edge")
					if lead_val < 0:
						raise ValueError("Lead edge must be >= 0.")
					self.inst.write(f":SOUR1:PULS:TRANsition:LEADing {lead_val}")
				if trail_txt:
					trail_val = self._parse_time_to_seconds(trail_txt, field_name="Trail edge")
					if trail_val < 0:
						raise ValueError("Trail edge must be >= 0.")
					self.inst.write(f":SOUR1:PULS:TRANsition:TRAiling {trail_val}")
			else:
				if lead_txt and trail_txt and lead_txt != trail_txt:
					raise ValueError("In 'Both' mode, lead and trail entries must match (or leave blank).")
				shared_txt = lead_txt or trail_txt
				if shared_txt:
					edge_val = self._parse_time_to_seconds(shared_txt, field_name="Edge time")
					if edge_val < 0:
						raise ValueError("Edge time must be >= 0.")
					self.inst.write(f":SOUR1:PULS:TRANsition:LEADing {edge_val}")
					self.inst.write(f":SOUR1:PULS:TRANsition:TRAiling {edge_val}")

			if is_burst:
				self.inst.write(":SOUR1:BURSt:STAT ON")
				self.inst.write(":SOUR1:BURSt:MODE TRIG")
				self.inst.write(f":SOUR1:BURSt:NCYC {burst_count}")
				self.inst.write(":TRIG1:SOUR BUS")
				self.inst.write(":INIT1:CONT OFF")
			else:
				self.inst.write(":SOUR1:BURSt:STAT OFF")
				self.inst.write(":INIT1:CONT ON")
				self.inst.write(":TRIG1:SOUR IMM")
			self.inst.write(":OUTP1 OFF")

			self.inst.write("*WAI")
			self.ch1_configured = True
			self.ch1_output_on = False
			self.ch1_is_burst = is_burst
			self._update_ch1_button_label()
			self.btn_ch1_toggle.configure(state=tk.NORMAL)
			unit_label = "Vpp" if amp_unit == "VPP" else "Vrms"
			mode_label = "Burst" if is_burst else "Continuous"
			status = (
				f"Channel 1 pulse ready: {freq} Hz, width {width:g} s, amplitude {amplitude} {unit_label}, offset {offset} V, mode {mode_label}."
			)
			self._log(status)
			if is_burst:
				self._log(f"Channel 1 set for BUS-triggered {burst_count}-cycle burst.")
			else:
				self._log("Channel 1 configured for continuous output.")
			if not silent:
				self._log("Channel 1 pulse configured (output OFF).")
			try:
				if self.ch1_is_burst:
					self._ensure_ch1_output_on()
			except Exception:
				pass
			return True
		except ValueError as exc:
			self._log("Channel 1 configure error:", exc)
			if not silent:
				messagebox.showerror("Channel 1", str(exc))
		except Exception as exc:
			self._log("Channel 1 configure failed:", exc)
			if not silent:
				messagebox.showerror("Channel 1", str(exc))
		return False

	def _set_ch1_trigger_delay(self, delay_seconds: float) -> None:
		if not self.inst or not self.ch1_configured:
			return
		if not self.ch1_is_burst:
			self._log("Channel 1 is in continuous mode; trigger delay ignored.")
			return
		seconds = max(0.0, float(delay_seconds))
		try:
			self.inst.write(f":TRIG1:DELay {seconds}")
			self._log(f"Channel 1 trigger delay set to {seconds:.6f}s relative to Channel 2 trigger.")
		except Exception as exc:
			self._log(f"Unable to program Channel 1 trigger delay ({seconds:.6f}s): {exc}")

	def fire_pulse(self) -> None:
		if not self.configured or not self.inst:
			messagebox.showwarning("Keysight", "Configure channel 2 first.")
			return
		try:
			cycles = int(float(self.cycles_var.get()))
			freq = float(self.freq_var.get())
			settle = float(self.settle_var.get())
		except ValueError:
			messagebox.showerror("Keysight", "Invalid numeric values.")
			return

		duration = max(1e-4, cycles / freq)
		dwell = max(0.01, duration * settle)

		phase_text = self.phase_delay_var.get().strip()
		if phase_text:
			try:
				phase_delay = max(0.0, float(phase_text))
			except ValueError:
				messagebox.showerror("Keysight", "Phase delay must be numeric.")
				return
		else:
			phase_delay = dwell

		try:
			if not self.output_on:
				self.inst.write(":OUTP2 ON")
				self.output_on = True
				self.btn_toggle.configure(text="Ch2 Output ON")
			if self.ch1_configured:
				if self.ch1_is_burst:
					self._set_ch1_trigger_delay(phase_delay)
				elif phase_delay > 0:
					self._log("Channel 1 continuous mode active; phase delay ignored.")
				self._ensure_ch1_output_on()
			else:
				if phase_delay > 0:
					self._log("Phase delay ignored because Channel 1 is not configured.")

			def launch_pulse() -> None:
				self.inst.write(":INIT2:IMM")
				self.inst.write("*TRG")
				self._log(
					f"Burst triggered: {cycles} cycle(s) ({duration*1e3:.3f} ms). Ch1 delay={phase_delay:.6f}s."
				)
				self.parent.after(int(dwell * 1000), self._auto_off_after_fire)

			launch_pulse()
		except Exception as exc:
			self._log("Pulse failed:", exc)
			messagebox.showerror("Keysight", str(exc))

	def _auto_off_after_fire(self) -> None:
		if self.configured and not self.output_on:
			return
		try:
			if self.inst and self.output_on:
				self.inst.write(":OUTP2 OFF")
				self.output_on = False
				self.btn_toggle.configure(text="Ch2 Output OFF")
				self._log("Channel 2 automatically turned OFF after burst.")
		except Exception:
			pass

	def stop(self) -> None:
		if not self.inst:
			return
		try:
			self.inst.write(":OUTP2 OFF")
			self.inst.write(":SOUR2:BURSt:STAT OFF")
			self.inst.write(":INIT2:CONT OFF")
			self.output_on = False
			self.btn_toggle.configure(text="Ch2 Output OFF")
			self._log("Channel 2 output disabled.")
		except Exception as exc:
			self._log("Stop failed:", exc)

	def toggle_output(self) -> None:
		if not self.inst or not self.configured:
			return
		desired = not self.output_on
		try:
			self.inst.write(":OUTP2 ON" if desired else ":OUTP2 OFF")
			self.output_on = desired
			label = "Ch2 Output ON" if desired else "Ch2 Output OFF"
			self.btn_toggle.configure(text=label)
			self._log(f"Channel 2 output {label.split()[-1]}.")
		except Exception as exc:
			self._log("Toggle failed:", exc)

	def toggle_ch1_output(self) -> None:
		if not self.inst or not self.connected or not self.ch1_configured:
			return
		desired = not self.ch1_output_on
		try:
			self.inst.write(":OUTP1 ON" if desired else ":OUTP1 OFF")
			self.ch1_output_on = desired
			self._update_ch1_button_label()
			self._log(f"Channel 1 output {'ON' if desired else 'OFF'}.")
		except Exception as exc:
			messagebox.showerror("Channel 1", str(exc))
			self._log("Channel 1 toggle failed:", exc)

	def query_ch1_status(self) -> None:
		if not self.inst or not self.connected:
			messagebox.showwarning("Channel 1", "Connect first.")
			return
		try:
			def ask(cmd: str) -> str:
				assert self.inst
				return self.inst.query(cmd).strip()

			func = ask(":SOUR1:FUNC?")
			period = ask(":SOUR1:PULS:PER?")
			width = ask(":SOUR1:PULS:WIDTh?")
			high = ask(":SOUR1:VOLT:HIGH?")
			low = ask(":SOUR1:VOLT:LOW?")
			try:
				lead = ask(":SOUR1:PULS:TRANsition:LEADing?")
			except Exception:
				lead = "(n/a)"
			try:
				trail = ask(":SOUR1:PULS:TRANsition:TRAiling?")
			except Exception:
				trail = "(n/a)"
			load = ask(":OUTP1:LOAD?")
			outp = ask(":OUTP1?")
			for line in (
				"Channel 1 status:",
				f"  Function: {func}",
				f"  Period: {period} s",
				f"  Width: {width} s",
				f"  High: {high} V  Low: {low} V",
				f"  Lead: {lead} s  Trail: {trail} s",
				f"  Load: {load}",
				f"  Output: {outp}",
			):
				self._log(line)
		except Exception as exc:
			messagebox.showerror("Channel 1", str(exc))
			self._log("Channel 1 query failed:", exc)


class CombinedMeasurementApp:
	"""Hosts both instrument panels side by side in a single window."""

	def __init__(self) -> None:
		self.root = tk.Tk()
		self.root.title("Keysight 33522B + Keithley 2602B Control")
		self.root.geometry("1600x900")
		self.root.minsize(1200, 800)

		paned = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
		paned.pack(fill=tk.BOTH, expand=True)

		left_frame = ttk.Frame(paned)
		right_frame = ttk.Frame(paned)
		paned.add(left_frame, weight=1)
		paned.add(right_frame, weight=1)

		self.keysight_panel = KeysightPulsePanel(left_frame)
		self.keithley_panel = KeithleyVoltmeterPanel(right_frame)

		self.root.protocol("WM_DELETE_WINDOW", self.on_close)

	def on_close(self) -> None:
		try:
			self.keysight_panel.shutdown_outputs()
		except Exception:
			pass
		try:
			self.keysight_panel.disconnect()
		except Exception:
			pass
		try:
			self.keithley_panel.shutdown()
		except Exception:
			pass
		self.root.destroy()

	def run(self) -> None:
		self.root.mainloop()


def main() -> None:
	CombinedMeasurementApp().run()


if __name__ == "__main__":
	main()
