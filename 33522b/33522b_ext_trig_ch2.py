import math
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import pyvisa

DEFAULT_ADDR = "TCPIP0::169.254.5.22::5025::SOCKET"
DEFAULT_FREQ = "1000"  # Hz for ch2
DEFAULT_VPP = "4.2"  # Vpp for ch2
DEFAULT_CYCLES = "1"  # burst cycles per trigger
DEFAULT_SETTLE = "1.2"  # multiplier * burst duration before re-arm
DEFAULT_CH1_FREQ = "1000"
DEFAULT_CH1_WIDTH = "0.5e-3"
DEFAULT_CH1_HIGH = "0.5"
DEFAULT_CH1_LOW = "-0.5"
DEFAULT_CH1_LOAD = "INF"
DEFAULT_CH1_PHASE = "0"
DEFAULT_CH1_LEAD = ""
DEFAULT_CH1_TRAIL = ""
DEFAULT_CH1_EDGE_MODE = "Both"


class Channel2TriggerGui:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("33522B Channel 2 Pulse Trigger")

        self.rm = None
        self.inst = None
        self.connected = False
        self.configured = False

        self.addr_var = tk.StringVar(value=DEFAULT_ADDR)
        self.freq_var = tk.StringVar(value=DEFAULT_FREQ)
        self.vpp_var = tk.StringVar(value=DEFAULT_VPP)
        self.cycles_var = tk.StringVar(value=DEFAULT_CYCLES)
        self.settle_var = tk.StringVar(value=DEFAULT_SETTLE)
        self.pulse_hint_var = tk.StringVar()
        self.ch1_freq_var = tk.StringVar(value=DEFAULT_CH1_FREQ)
        self.ch1_width_var = tk.StringVar(value=DEFAULT_CH1_WIDTH)
        self.ch1_high_var = tk.StringVar(value=DEFAULT_CH1_HIGH)
        self.ch1_low_var = tk.StringVar(value=DEFAULT_CH1_LOW)
        self.ch1_load_var = tk.StringVar(value=DEFAULT_CH1_LOAD)
        self.ch1_phase_var = tk.StringVar(value=DEFAULT_CH1_PHASE)
        self.ch1_lead_var = tk.StringVar(value=DEFAULT_CH1_LEAD)
        self.ch1_trail_var = tk.StringVar(value=DEFAULT_CH1_TRAIL)
        self.ch1_edge_mode_var = tk.StringVar(value=DEFAULT_CH1_EDGE_MODE)
        self.ch1_period_hint_var = tk.StringVar(value="Period: —")

        self.last_freq = None
        self.last_vpp = None
        self.last_cycles = None
        self.last_settle = None
        self.output_on = False
        self.ch1_output_on = False
        self.ch1_configured = False

        main = ttk.Frame(root, padding=10)
        main.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        row = 0
        ttk.Label(main, text="VISA Address").grid(row=row, column=0, sticky="e")
        ttk.Entry(main, textvariable=self.addr_var, width=42).grid(
            row=row, column=1, columnspan=3, sticky="we"
        )
        row += 1

        cfg = ttk.LabelFrame(main, text="Channel 2 Pulse Settings")
        cfg.grid(row=row, column=0, columnspan=4, sticky="we")
        row += 1

        ttk.Label(cfg, text="Frequency (Hz)").grid(row=0, column=0, sticky="e")
        ttk.Entry(cfg, textvariable=self.freq_var, width=14).grid(row=0, column=1, sticky="w")

        ttk.Label(cfg, text="Amplitude (Vpp)").grid(row=0, column=2, sticky="e")
        ttk.Entry(cfg, textvariable=self.vpp_var, width=10).grid(row=0, column=3, sticky="w")

        ttk.Label(cfg, text="Burst cycles").grid(row=0, column=4, sticky="e")
        ttk.Entry(cfg, textvariable=self.cycles_var, width=8).grid(row=0, column=5, sticky="w")

        ttk.Label(cfg, text="Settle factor").grid(row=1, column=0, sticky="e")
        ttk.Entry(cfg, textvariable=self.settle_var, width=14).grid(row=1, column=1, sticky="w")

        ttk.Label(cfg, textvariable=self.pulse_hint_var).grid(
            row=1, column=2, columnspan=4, sticky="w", pady=(0, 2)
        )

        for c in range(6):
            cfg.columnconfigure(c, weight=1)

        btns = ttk.Frame(main)
        btns.grid(row=row, column=0, columnspan=4, sticky="we", pady=(8, 0))
        row += 1
        self.btn_connect = ttk.Button(btns, text="Connect", command=self.connect)
        self.btn_connect.grid(row=0, column=0, padx=4)
        self.btn_disconnect = ttk.Button(btns, text="Disconnect", command=self.disconnect, state="disabled")
        self.btn_disconnect.grid(row=0, column=1, padx=4)
        self.btn_configure = ttk.Button(btns, text="Configure Channel 2", command=self.configure, state="disabled")
        self.btn_configure.grid(row=0, column=2, padx=4)
        self.btn_fire = ttk.Button(btns, text="Send Pulse", command=self.fire_pulse, state="disabled")
        self.btn_fire.grid(row=0, column=3, padx=4)
        self.btn_stop = ttk.Button(btns, text="Stop Output", command=self.stop, state="disabled")
        self.btn_stop.grid(row=0, column=4, padx=4)
        self.btn_output_toggle = ttk.Button(
            btns, text="Ch2 Output OFF", command=self.toggle_output, state="disabled"
        )
        self.btn_output_toggle.grid(row=0, column=5, padx=4)
        ttk.Button(btns, text="Error Window", command=self.open_error_window).grid(row=0, column=6, padx=4)
        for c in range(7):
            btns.columnconfigure(c, weight=1)

        ch1_frame = ttk.LabelFrame(main, text="Channel 1 Pulse Settings")
        ch1_frame.grid(row=row, column=0, columnspan=4, sticky="we", pady=(10, 0))
        row += 1

        ttk.Label(ch1_frame, text="Frequency (Hz)").grid(row=0, column=0, sticky="e")
        freq_frame = ttk.Frame(ch1_frame)
        freq_frame.grid(row=0, column=1, sticky="w")
        ttk.Entry(freq_frame, textvariable=self.ch1_freq_var, width=14).pack(side=tk.LEFT)
        ttk.Label(freq_frame, textvariable=self.ch1_period_hint_var).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(ch1_frame, text="Pulse width (s or SI)").grid(row=0, column=2, sticky="e")
        ttk.Entry(ch1_frame, textvariable=self.ch1_width_var, width=14).grid(row=0, column=3, sticky="w")

        ttk.Label(ch1_frame, text="High level (V)").grid(row=1, column=0, sticky="e")
        ttk.Entry(ch1_frame, textvariable=self.ch1_high_var, width=14).grid(row=1, column=1, sticky="w")
        ttk.Label(ch1_frame, text="Low level (V)").grid(row=1, column=2, sticky="e")
        ttk.Entry(ch1_frame, textvariable=self.ch1_low_var, width=14).grid(row=1, column=3, sticky="w")

        ttk.Label(ch1_frame, text="Load (Ω or INF)").grid(row=2, column=0, sticky="e")
        ttk.Entry(ch1_frame, textvariable=self.ch1_load_var, width=14).grid(row=2, column=1, sticky="w")
        ttk.Label(ch1_frame, text="Phase (deg)").grid(row=2, column=2, sticky="e")
        ttk.Entry(ch1_frame, textvariable=self.ch1_phase_var, width=14).grid(row=2, column=3, sticky="w")

        ttk.Label(ch1_frame, text="Lead edge (s)").grid(row=3, column=0, sticky="e")
        ttk.Entry(ch1_frame, textvariable=self.ch1_lead_var, width=14).grid(row=3, column=1, sticky="w")
        ttk.Label(ch1_frame, text="Trail edge (s)").grid(row=3, column=2, sticky="e")
        ttk.Entry(ch1_frame, textvariable=self.ch1_trail_var, width=14).grid(row=3, column=3, sticky="w")
        ttk.Label(ch1_frame, text="Edge mode").grid(row=3, column=4, sticky="e")
        tk.OptionMenu(ch1_frame, self.ch1_edge_mode_var, "Both", "Separate").grid(
            row=3, column=5, sticky="w"
        )

        btn_row = ttk.Frame(ch1_frame)
        btn_row.grid(row=4, column=0, columnspan=6, sticky="we", pady=(6, 0))
        self.btn_ch1_configure = ttk.Button(
            btn_row, text="Apply Ch1 Pulse", command=self.configure_ch1, state="disabled"
        )
        self.btn_ch1_configure.pack(side=tk.LEFT)
        self.btn_ch1_toggle = ttk.Button(
            btn_row, text="Ch1 Output OFF", command=self.toggle_ch1_output, state="disabled"
        )
        self.btn_ch1_toggle.pack(side=tk.LEFT, padx=6)
        self.btn_ch1_query = ttk.Button(
            btn_row, text="Query Ch1", command=self.query_ch1_status, state="disabled"
        )
        self.btn_ch1_query.pack(side=tk.LEFT)

        for c in range(6):
            ch1_frame.columnconfigure(c, weight=1)

        self.log = scrolledtext.ScrolledText(main, width=76, height=14, state="disabled")
        self.log.grid(row=row, column=0, columnspan=4, sticky="nsew", pady=(8, 0))
        main.rowconfigure(row, weight=1)

        row += 1
        status = ttk.Frame(main)
        status.grid(row=row, column=0, columnspan=4, sticky="we", pady=(6, 0))
        self.status_var = tk.StringVar(value="Disconnected")
        ttk.Label(status, textvariable=self.status_var, anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.err_win = None
        self.err_text = None

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

        root.protocol("WM_DELETE_WINDOW", self.on_close)

    # --- Utility ---------------------------------------------------------
    def log_print(self, *parts) -> None:
        msg = " ".join(str(p) for p in parts)
        self.log.configure(state="normal")
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)
        self.log.configure(state="disabled")

    def _ensure(self) -> None:
        if not (self.connected and self.inst):
            raise RuntimeError("Instrument is not connected.")

    def safe_write(self, command: str) -> None:
        self._ensure()
        self.log_print(">>", command)
        self.inst.write(command)

    def safe_query(self, command: str, *, retries: int = 1) -> str:
        self._ensure()
        last_exc = None
        for attempt in range(1, retries + 1):
            try:
                self.log_print("?>", command)
                resp = self.inst.query(command).strip()
                self.log_print("<<", resp)
                return resp
            except pyvisa.VisaIOError as exc:
                last_exc = exc
                self.log_print(
                    f"Query attempt {attempt} for '{command}' timed out ({exc}). Retrying..."
                )
                try:
                    self.inst.clear()
                except Exception:
                    pass
                time.sleep(0.05)
        if last_exc is None:
            raise RuntimeError("Query failed for unknown reasons.")
        raise last_exc

    def _set_button_states(self, connected: bool, configured: bool) -> None:
        self.btn_connect.configure(state="disabled" if connected else "normal")
        self.btn_disconnect.configure(state="normal" if connected else "disabled")
        self.btn_configure.configure(state="normal" if connected else "disabled")
        self.btn_fire.configure(state="normal" if configured else "disabled")
        self.btn_stop.configure(state="normal" if configured else "disabled")
        self.btn_output_toggle.configure(state="normal" if configured else "disabled")
        self.btn_ch1_configure.configure(state="normal" if connected else "disabled")
        self.btn_ch1_toggle.configure(
            state="normal" if connected and self.ch1_configured else "disabled"
        )
        self.btn_ch1_query.configure(state="normal" if connected else "disabled")

    def _update_output_button_label(self) -> None:
        label = "Ch2 Output ON" if self.output_on else "Ch2 Output OFF"
        self.btn_output_toggle.configure(text=label)

    def _update_ch1_button_label(self) -> None:
        label = "Ch1 Output ON" if self.ch1_output_on else "Ch1 Output OFF"
        self.btn_ch1_toggle.configure(text=label)

    def _update_hint(self) -> None:
        txt = self.freq_var.get().strip()
        if not txt:
            self.pulse_hint_var.set("")
            return
        try:
            freq = float(txt)
        except ValueError:
            self.pulse_hint_var.set("Enter frequency > 0 to estimate pulse width.")
            return
        if freq <= 0:
            self.pulse_hint_var.set("Enter frequency > 0 to estimate pulse width.")
            return
        period = 1.0 / freq
        high_time = period / 2.0
        self.pulse_hint_var.set(f"One cycle ≈ {period*1e3:.3f} ms, high ~ {high_time*1e3:.3f} ms.")

    def _update_ch1_period_hint(self) -> None:
        txt = self.ch1_freq_var.get().strip()
        if not txt:
            self.ch1_period_hint_var.set("Period: —")
            return
        try:
            freq = float(txt)
        except ValueError:
            self.ch1_period_hint_var.set("Period: —")
            return
        if freq <= 0:
            self.ch1_period_hint_var.set("Period: —")
            return
        period = 1.0 / freq
        self.ch1_period_hint_var.set(f"Period ≈ {self._format_seconds_si(period)}")

    @staticmethod
    def _format_seconds_si(seconds: float) -> str:
        try:
            value = float(seconds)
        except (TypeError, ValueError):
            return "—"
        if value <= 0 or not math.isfinite(value):
            return "—"
        if value >= 1:
            return f"{value:g} s"
        if value >= 1e-3:
            return f"{value*1e3:g} ms"
        if value >= 1e-6:
            return f"{value*1e6:g} µs"
        if value >= 1e-9:
            return f"{value*1e9:g} ns"
        return f"{value*1e12:g} ps"

    @staticmethod
    def _parse_time_to_seconds(text: str, *, field_name: str) -> float:
        raw = str(text).strip().lower().replace(" ", "")
        if not raw:
            raise ValueError(f"{field_name} is required.")
        units = {
            "s": 1.0,
            "ms": 1e-3,
            "us": 1e-6,
            "µs": 1e-6,
            "ns": 1e-9,
            "ps": 1e-12,
        }
        for suffix in sorted(units, key=len, reverse=True):
            if raw.endswith(suffix):
                number = float(raw[: -len(suffix)])
                return number * units[suffix]
        return float(raw)

    def _set_ch1_load(self, load_text: str) -> None:
        self._ensure()
        load = str(load_text).strip().upper()
        if load in {"INF", "INFINITE", "HIGHZ", "HZ"}:
            self.safe_write(":OUTP1:LOAD INF")
            return
        try:
            value = float(load)
        except ValueError as exc:
            raise ValueError("Channel 1 load must be INF or numeric.") from exc
        if value <= 0:
            raise ValueError("Channel 1 load must be greater than 0 Ω.")
        self.safe_write(f":OUTP1:LOAD {value}")

    @staticmethod
    def _parse_float(text: str, name: str) -> float:
        try:
            value = float(str(text).strip())
        except ValueError as exc:
            raise ValueError(f"{name} must be a number.") from exc
        return value

    @classmethod
    def _parse_positive(cls, text: str, name: str) -> float:
        value = cls._parse_float(text, name)
        if value <= 0:
            raise ValueError(f"{name} must be > 0.")
        return value

    @staticmethod
    def _parse_int(text: str, name: str) -> int:
        try:
            value = int(str(text).strip())
        except ValueError as exc:
            raise ValueError(f"{name} must be an integer.") from exc
        if value <= 0:
            raise ValueError(f"{name} must be > 0.")
        return value

    # --- VISA lifecycle --------------------------------------------------
    def connect(self) -> None:
        if self.connected:
            return
        try:
            if not self.rm:
                self.rm = pyvisa.ResourceManager()
            address = self.addr_var.get().strip()
            if not address:
                raise ValueError("Enter a VISA address.")
            self.log_print(f"Connecting to {address} ...")
            self.inst = self.rm.open_resource(address, timeout=5000)
            self.inst.write_termination = "\n"
            self.inst.read_termination = "\n"
            idn = self.inst.query("*IDN?").strip()
            self.log_print("Connected:", idn)
            self.status_var.set(f"Connected to {idn}")
            self.connected = True
            self.configured = False
            self._set_button_states(connected=True, configured=False)
        except Exception as exc:
            self.log_print("Connect failed:", exc)
            messagebox.showerror("Connect", str(exc))
            if self.inst:
                try:
                    self.inst.close()
                except Exception:
                    pass
            self.inst = None
            self.connected = False
            self._set_button_states(connected=False, configured=False)

    def disconnect(self) -> None:
        if not self.connected:
            return
        try:
            self.stop()
        except Exception:
            pass
        try:
            if self.inst:
                self.safe_write(":OUTP1 OFF")
        except Exception:
            pass
        try:
            if self.inst:
                self.inst.close()
        finally:
            self.inst = None
            self.connected = False
            self.configured = False
            self.output_on = False
            self.ch1_output_on = False
            self.ch1_configured = False
            self._update_output_button_label()
            self._update_ch1_button_label()
            self.status_var.set("Disconnected")
            self._set_button_states(connected=False, configured=False)
            self.log_print("Disconnected.")
            self.last_freq = None
            self.last_vpp = None
            self.last_cycles = None
            self.last_settle = None

    # --- Instrument actions ----------------------------------------------
    def configure(self) -> None:
        try:
            self._ensure()
            freq = self._parse_positive(self.freq_var.get(), "Frequency")
            vpp = self._parse_positive(self.vpp_var.get(), "Amplitude")
            cycles = self._parse_int(self.cycles_var.get(), "Burst cycles")
            settle = self._parse_positive(self.settle_var.get(), "Settle factor")

            if vpp > 10:
                raise ValueError("Amplitude exceeds 10 Vpp. Reduce value to stay within instrument limits.")

            low_level = 0.0
            high_level = vpp
            offset = vpp / 2.0

            self.log_print("Configuring channel 2 pulse source ...")
            self.safe_write("*CLS")
            self.safe_write(":SOUR2:FUNC SQU")
            self.safe_write(f":SOUR2:FREQ {freq}")
            self.safe_write(f":SOUR2:VOLT:LOW {low_level}")
            self.safe_write(f":SOUR2:VOLT:HIGH {high_level}")
            self.safe_write(f":SOUR2:VOLT:OFFS {offset}")
            self.safe_write(":SOUR2:PULS:DCYC 50")
            self.safe_write(":OUTP2:LOAD INF")

            self.safe_write(":SOUR2:BURSt:STAT ON")
            self.safe_write(":SOUR2:BURSt:MODE TRIG")
            self.safe_write(f":SOUR2:BURSt:NCYC {cycles}")
            self.safe_write(":TRIG2:SOUR BUS")
            self.safe_write(":INIT2:CONT OFF")

            self.safe_write(":OUTP2 OFF")
            self.output_on = False
            self._update_output_button_label()

            self.log_print(
                f"Channel 2 ready: {freq} Hz square, {vpp} Vpp (0-{vpp} V), burst cycles {cycles}. "
                "Output stays OFF until you click 'Send Pulse'."
            )
            self.status_var.set("Channel 2 configured (output OFF).")
            self._set_button_states(connected=True, configured=True)
            self.connected = True
            self.configured = True
            self.last_freq = freq
            self.last_vpp = vpp
            self.last_cycles = cycles
            self.last_settle = settle
        except Exception as exc:
            self.log_print("Configure failed:", exc)
            messagebox.showerror("Configure", str(exc))

    def configure_ch1(self) -> None:
        try:
            self._ensure()
            freq = self._parse_positive(self.ch1_freq_var.get(), "Channel 1 frequency")
            width = self._parse_time_to_seconds(self.ch1_width_var.get(), field_name="Pulse width")
            high_level = self._parse_float(self.ch1_high_var.get(), "High level")
            low_level = self._parse_float(self.ch1_low_var.get(), "Low level")
            load_text = self.ch1_load_var.get()
            phase = self._parse_float(self.ch1_phase_var.get(), "Phase")
            lead_txt = self.ch1_lead_var.get().strip()
            trail_txt = self.ch1_trail_var.get().strip()
            mode = self.ch1_edge_mode_var.get().strip().lower()

            period = 1.0 / freq
            if not (0 < width < period):
                raise ValueError("Pulse width must be greater than 0 and less than the period.")
            if high_level <= low_level:
                raise ValueError("High level must be greater than low level.")

            self.log_print("Configuring channel 1 pulse ...")
            self.safe_write(":OUTP1 OFF")
            self._set_ch1_load(load_text)
            self.safe_write(":SOUR1:FUNC PULS")
            self.safe_write(f":SOUR1:PULS:PER {period}")
            self.safe_write(f":SOUR1:PULS:WIDTh {width}")
            self.safe_write(f":SOUR1:VOLT:HIGH {high_level}")
            self.safe_write(f":SOUR1:VOLT:LOW {low_level}")
            self.safe_write(f":SOUR1:PHAS {phase}")

            if mode == "separate":
                if lead_txt:
                    lead_val = self._parse_time_to_seconds(lead_txt, field_name="Lead edge")
                    if lead_val < 0:
                        raise ValueError("Lead edge time must be >= 0.")
                    self.safe_write(f":SOUR1:PULS:TRANsition:LEADing {lead_val}")
                if trail_txt:
                    trail_val = self._parse_time_to_seconds(trail_txt, field_name="Trail edge")
                    if trail_val < 0:
                        raise ValueError("Trail edge time must be >= 0.")
                    self.safe_write(f":SOUR1:PULS:TRANsition:TRAiling {trail_val}")
            else:
                if lead_txt and trail_txt and lead_txt != trail_txt:
                    raise ValueError("In 'Both' mode, lead and trail entries must match (or leave one blank).")
                shared_txt = lead_txt or trail_txt
                if shared_txt:
                    edge_val = self._parse_time_to_seconds(shared_txt, field_name="Edge time")
                    if edge_val < 0:
                        raise ValueError("Edge time must be >= 0.")
                    self.safe_write(f":SOUR1:PULS:TRANsition:LEADing {edge_val}")
                    self.safe_write(f":SOUR1:PULS:TRANsition:TRAiling {edge_val}")

            self.safe_write("*WAI")
            self.ch1_configured = True
            self.ch1_output_on = False
            self._update_ch1_button_label()
            self._set_button_states(connected=True, configured=self.configured)
            self.status_var.set("Channel 1 pulse configured (output OFF).")
            self.log_print(
                f"Channel 1 pulse ready: {freq} Hz, width {width:g} s, high {high_level} V, low {low_level} V."
            )
        except Exception as exc:
            self.log_print("Channel 1 configure failed:", exc)
            messagebox.showerror("Configure Channel 1", str(exc))

    def fire_pulse(self) -> None:
        try:
            self._ensure()
            if not self.configured:
                raise RuntimeError("Configure channel 2 first.")

            freq = self._parse_positive(self.freq_var.get(), "Frequency")
            vpp = self._parse_positive(self.vpp_var.get(), "Amplitude")
            cycles = self._parse_int(self.cycles_var.get(), "Burst cycles")
            settle = self._parse_positive(self.settle_var.get(), "Settle factor")

            if abs(freq - (self.last_freq or math.inf)) > 1e-9:
                self.safe_write(f":SOUR2:FREQ {freq}")
                self.safe_write(f":SOUR2:BURSt:NCYC {cycles}")
            if abs(vpp - (self.last_vpp or math.inf)) > 1e-9:
                self.safe_write(f":SOUR2:VOLT:LOW 0")
                self.safe_write(f":SOUR2:VOLT:HIGH {vpp}")
                self.safe_write(f":SOUR2:VOLT:OFFS {vpp / 2.0}")
            if cycles != (self.last_cycles or None):
                self.safe_write(f":SOUR2:BURSt:NCYC {cycles}")

            self.last_freq = freq
            self.last_vpp = vpp
            self.last_cycles = cycles
            self.last_settle = settle

            duration = cycles / freq
            dwell = max(0.01, duration * settle)

            was_output_on = self.output_on
            if not was_output_on:
                self.safe_write(":OUTP2 ON")
                self.output_on = True
                self._update_output_button_label()
            else:
                self.safe_write(":OUTP2 ON")

            self.safe_write(":INIT2:IMM")
            self.safe_write("*TRG")
            self.log_print(f"Triggered burst: {cycles} cycle(s) at {freq} Hz ({duration*1e3:.3f} ms).")
            time.sleep(dwell)
            if not was_output_on:
                self.safe_write(":OUTP2 OFF")
                self.output_on = False
                self._update_output_button_label()

        except Exception as exc:
            self.log_print("Pulse failed:", exc)
            messagebox.showerror("Send Pulse", str(exc))

    def stop(self) -> None:
        if not self.connected or not self.inst:
            return
        try:
            self.safe_write(":OUTP2 OFF")
            self.output_on = False
            self._update_output_button_label()
            self.safe_write(":SOUR2:BURSt:STAT OFF")
            self.safe_write(":TRIG2:SOUR BUS")
            self.safe_write(":INIT2:CONT OFF")
            self.configured = False
            self._set_button_states(connected=True, configured=False)
            self.status_var.set("Channel 2 output OFF.")
            self.log_print("Channel 2 disabled.")
        except Exception as exc:
            self.log_print("Stop failed:", exc)
            messagebox.showerror("Stop Output", str(exc))

    def toggle_output(self) -> None:
        if not self.connected or not self.configured or not self.inst:
            return
        try:
            desired_on = not self.output_on
            self.safe_write(":OUTP2 ON" if desired_on else ":OUTP2 OFF")
            self.output_on = desired_on
            self._update_output_button_label()
            state_text = "ON" if desired_on else "OFF"
            self.status_var.set(f"Channel 2 output {state_text.lower()}.")
            self.log_print(f"Channel 2 output turned {state_text}.")
        except Exception as exc:
            self.log_print("Toggle output failed:", exc)
            messagebox.showerror("Ch2 Output", str(exc))

    def toggle_ch1_output(self) -> None:
        if not self.connected or not self.ch1_configured or not self.inst:
            return
        try:
            desired_on = not self.ch1_output_on
            self.safe_write(":OUTP1 ON" if desired_on else ":OUTP1 OFF")
            self.ch1_output_on = desired_on
            self._update_ch1_button_label()
            state = "ON" if desired_on else "OFF"
            self.status_var.set(f"Channel 1 output {state.lower()}.")
            self.log_print(f"Channel 1 output turned {state}.")
        except Exception as exc:
            self.log_print("Ch1 toggle failed:", exc)
            messagebox.showerror("Ch1 Output", str(exc))

    def query_ch1_status(self) -> None:
        try:
            self._ensure()
            func = self.safe_query(":SOUR1:FUNC?", retries=2)
            per = self.safe_query(":SOUR1:PULS:PER?", retries=2)
            width = self.safe_query(":SOUR1:PULS:WIDTh?", retries=2)
            high = self.safe_query(":SOUR1:VOLT:HIGH?", retries=2)
            low = self.safe_query(":SOUR1:VOLT:LOW?", retries=2)
            try:
                lead = self.safe_query(":SOUR1:PULS:TRANsition:LEADing?", retries=2)
            except Exception:
                lead = "(n/a)"
            try:
                trail = self.safe_query(":SOUR1:PULS:TRANsition:TRAiling?", retries=2)
            except Exception:
                trail = "(n/a)"
            load = self.safe_query(":OUTP1:LOAD?", retries=2)
            outp = self.safe_query(":OUTP1?", retries=2)
            lines = [
                "Channel 1 status:",
                f"  Function: {func}",
                f"  Period: {per} s",
                f"  Width: {width} s",
                f"  High: {high} V  Low: {low} V",
                f"  Lead: {lead} s  Trail: {trail} s",
                f"  Load: {load}",
                f"  Output: {outp}",
            ]
            for line in lines:
                self.log_print(line)
        except Exception as exc:
            self.log_print("Channel 1 query failed:", exc)
            messagebox.showerror("Query Channel 1", str(exc))

    # --- Error window ----------------------------------------------------
    def open_error_window(self) -> None:
        if self.err_win and tk.Toplevel.winfo_exists(self.err_win):
            self.err_win.deiconify()
            self.err_win.lift()
            return

        self.err_win = tk.Toplevel(self.root)
        self.err_win.title("Instrument Errors")
        try:
            x = self.root.winfo_rootx() + self.root.winfo_width() + 10
            y = self.root.winfo_rooty()
            self.err_win.geometry(f"+{x}+{y}")
        except Exception:
            pass

        frame = ttk.Frame(self.err_win, padding=8)
        frame.pack(fill=tk.BOTH, expand=True)

        self.err_text = scrolledtext.ScrolledText(frame, width=60, height=18, state="normal")
        self.err_text.pack(fill=tk.BOTH, expand=True)

        controls = ttk.Frame(frame)
        controls.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(controls, text="Refresh", command=self.refresh_errors).pack(side=tk.LEFT)
        ttk.Button(controls, text="Clear", command=self.clear_error_window).pack(side=tk.LEFT, padx=6)

        def _close() -> None:
            try:
                self.err_win.destroy()
            finally:
                self.err_win = None
                self.err_text = None

        self.err_win.protocol("WM_DELETE_WINDOW", _close)
        self.refresh_errors()

    def refresh_errors(self) -> None:
        if not self.err_text:
            return
        if not self.connected or not self.inst:
            messagebox.showerror("Error Window", "Instrument is not connected.")
            return
        try:
            lines = []
            for _ in range(16):
                err = self.inst.query("SYST:ERR?").strip()
                lines.append(err)
                if err.startswith("0,"):
                    break
            self.err_text.insert(tk.END, "\n".join(lines) + "\n")
            self.err_text.see(tk.END)
        except Exception as exc:
            messagebox.showerror("Error Window", str(exc))

    def clear_error_window(self) -> None:
        if self.err_text:
            self.err_text.delete("1.0", tk.END)

    # --- Shutdown --------------------------------------------------------
    def on_close(self) -> None:
        try:
            self.disconnect()
        finally:
            if self.err_win and tk.Toplevel.winfo_exists(self.err_win):
                try:
                    self.err_win.destroy()
                except Exception:
                    pass
            self.err_win = None
            self.err_text = None
            self.root.destroy()


def main() -> None:
    root = tk.Tk()
    Channel2TriggerGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
