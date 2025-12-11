"""Standalone GUI for Keysight 33522B trigger/burst on CH2 plus DC level on CH1.

This mirrors the behaviour of ``33522b_trigger_and_pulse.py`` for the
Channel 2 trigger/burst controls, but the Channel 1 section now exposes a
DC level configuration similar to ``test_33522b_dc_level_gui.py``.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import pyvisa

DEFAULT_KEYSIGHT_ADDRESS = "TCPIP0::169.254.5.22::5025::SOCKET"
DEFAULT_CH1_LEVEL = "0.5"
DEFAULT_CH1_LOAD = "INF"


class KeysightTriggerDcPanel:
    """Encapsulates CH2 burst controls and CH1 DC-level helpers."""

    def __init__(self, parent: tk.Misc) -> None:
        self.parent = parent
        self.rm: pyvisa.ResourceManager | None = None
        self.inst: pyvisa.resources.MessageBasedResource | None = None
        self.connected = False
        self.configured = False
        self.output_on = False
        self.ch1_output_on = False
        self.ch1_configured = False

        self.addr_var = tk.StringVar(value=DEFAULT_KEYSIGHT_ADDRESS)
        self.freq_var = tk.StringVar(value="1000")
        self.vpp_var = tk.StringVar(value="4.2")
        self.cycles_var = tk.StringVar(value="1")
        self.settle_var = tk.StringVar(value="1.2")
        self.phase_delay_var = tk.StringVar(value="1e-6")
        self.pulse_hint_var = tk.StringVar()

        self.ch1_level_var = tk.StringVar(value=DEFAULT_CH1_LEVEL)
        self.ch1_load_var = tk.StringVar(value=DEFAULT_CH1_LOAD)

        self._build_ui(parent)
        try:
            self.freq_var.trace_add("write", lambda *_: self._update_hint())
        except AttributeError:
            self.freq_var.trace("w", lambda *_: self._update_hint())
        self._update_hint()

    def _build_ui(self, frame: tk.Misc) -> None:
        container = ttk.Frame(frame, padding=10)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(1, weight=1)

        ttk.Label(container, text="VISA address:").grid(column=0, row=0, sticky="w")
        ttk.Entry(container, textvariable=self.addr_var, width=32).grid(
            column=1, row=0, sticky="we", padx=(4, 8)
        )
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

        ch1_frame = ttk.LabelFrame(container, text="Channel 1 DC Level")
        ch1_frame.grid(column=0, row=4, columnspan=2, sticky="ew", pady=(10, 0))
        for col in range(4):
            ch1_frame.columnconfigure(col, weight=1)

        ttk.Label(ch1_frame, text="DC level (V)").grid(column=0, row=0, sticky="e")
        ttk.Entry(ch1_frame, textvariable=self.ch1_level_var, width=12).grid(column=1, row=0, sticky="w")
        ttk.Label(ch1_frame, text="Load (Ω or INF)").grid(column=2, row=0, sticky="e")
        ttk.Entry(ch1_frame, textvariable=self.ch1_load_var, width=12).grid(column=3, row=0, sticky="w")

        ch1_btns = ttk.Frame(ch1_frame)
        ch1_btns.grid(column=0, row=1, columnspan=4, sticky="w", pady=(6, 0))
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
        self.pulse_hint_var.set(f"Period ≈ {period*1e3:.3f} ms")

    def _parse_positive(self, text: str, *, field_name: str) -> float:
        try:
            value = float(text.strip())
        except ValueError as exc:
            raise ValueError(f"{field_name} must be numeric.") from exc
        if value <= 0:
            raise ValueError(f"{field_name} must be > 0.")
        return value

    def _parse_int(self, text: str, *, field_name: str) -> int:
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
            raise ValueError("Channel 1 load must be greater than 0 Ω.")
        self.inst.write(f":OUTP1:LOAD {value}")

    def _update_ch1_button_label(self) -> None:
        label = "Ch1 Output ON" if self.ch1_output_on else "Ch1 Output OFF"
        self.btn_ch1_toggle.configure(text=label)

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
            self.btn_connect.configure(state="disabled")
            self.btn_disconnect.configure(state="normal")
            self.btn_configure.configure(state="normal")
            self.btn_ch1_configure.configure(state="normal")
            self.btn_ch1_query.configure(state="normal")
            self.btn_ch1_toggle.configure(state="disabled")
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
            if self.inst:
                self.inst.write(":OUTP1 OFF")
                self.inst.write(":OUTP2 OFF")
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
        self.btn_connect.configure(state="normal")
        self.btn_disconnect.configure(state="disabled")
        self.btn_configure.configure(state="disabled")
        self.btn_fire.configure(state="disabled")
        self.btn_stop.configure(state="disabled")
        self.btn_toggle.configure(state="disabled", text="Ch2 Output OFF")
        self.btn_ch1_configure.configure(state="disabled")
        self.btn_ch1_toggle.configure(state="disabled", text="Ch1 Output OFF")
        self.btn_ch1_query.configure(state="disabled")
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
            self.btn_fire.configure(state="normal")
            self.btn_stop.configure(state="normal")
            self.btn_toggle.configure(state="normal", text="Ch2 Output OFF")
            self._log(
                f"Ch2 configured: {freq} Hz, {vpp} Vpp, {cycles} cycle(s) per bus trigger."
            )
        except Exception as exc:
            self._log("Configure failed:", exc)
            messagebox.showerror("Keysight", str(exc))

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
            self.inst.write(":INIT2:IMM")
            self.inst.write("*TRG")
            self._log(
                f"Burst triggered: {cycles} cycle(s) ({duration*1e3:.3f} ms). Delay={phase_delay:.6f}s."
            )
            self.parent.after(int(dwell * 1000), self._auto_off_after_fire)
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

    def configure_ch1(self) -> None:
        if not self.connected or not self.inst:
            messagebox.showwarning("Channel 1", "Connect first.")
            return
        try:
            level = float(self.ch1_level_var.get())
            load_text = self.ch1_load_var.get()
            self._set_ch1_load(load_text)
            self.inst.write(":SOUR1:FUNC DC")
            self.inst.write(f":SOUR1:VOLT:OFFS {level}")
            self.inst.write(":OUTP1 OFF")
            self.ch1_configured = True
            self.ch1_output_on = False
            self._update_ch1_button_label()
            self.btn_ch1_toggle.configure(state="normal")
            self._log(f"Channel 1 DC level configured to {level} V")
        except ValueError as exc:
            self._log("Channel 1 configure error:", exc)
            messagebox.showerror("Channel 1", str(exc))
        except Exception as exc:
            self._log("Channel 1 configure failed:", exc)
            messagebox.showerror("Channel 1", str(exc))

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
            level = ask(":SOUR1:VOLT:OFFS?")
            load = ask(":OUTP1:LOAD?")
            outp = ask(":OUTP1?")
            for line in (
                "Channel 1 status:",
                f"  Function: {func}",
                f"  DC level: {level} V",
                f"  Load: {load}",
                f"  Output: {outp}",
            ):
                self._log(line)
        except Exception as exc:
            messagebox.showerror("Channel 1", str(exc))
            self._log("Channel 1 query failed:", exc)


class KeysightTriggerDcApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("33522B Trigger + DC Level")
        self.root.geometry("820x720")
        self.root.minsize(700, 600)
        self.panel = KeysightTriggerDcPanel(self.root)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_close(self) -> None:
        try:
            self.panel.disconnect()
        finally:
            self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    KeysightTriggerDcApp().run()


if __name__ == "__main__":
    main()
