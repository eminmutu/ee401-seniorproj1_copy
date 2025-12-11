import tkinter as tk
from tkinter import messagebox, scrolledtext
import pyvisa
import threading
import time

#this code works without any header errors!

# apply config turns the output on, it runs always so to turn it off you need to select "output off"
# query returns the current front panel config

# Simple GUI to configure a single-channel pulse on 33522B
# Style kept similar to list_instrument_gui.py (minimal, single window, basic widgets)

DEFAULT_ADDR = "TCPIP0::169.254.5.22::5025::SOCKET"
CHANNEL = 1
SOURCE = f":SOURce{CHANNEL}"
PULSE = f"{SOURCE}:FUNCtion:PULSe"
OUTPUT = f":OUTPut{CHANNEL}"


class PulseGui:
    def __init__(self, root):
        self.root = root
        self.root.title("33522B Pulse (Single) GUI")

        self.rm = None
        self.inst = None
        self.connected = False

        # Top controls
        frm = tk.Frame(root)
        frm.pack(padx=12, pady=10, fill=tk.X)

        # Address and discovery
        tk.Label(frm, text="VISA Address:").grid(row=0, column=0, sticky="w")
        self.addr_var = tk.StringVar(value=DEFAULT_ADDR)
        tk.Entry(frm, textvariable=self.addr_var, width=42).grid(
            row=0, column=1, sticky="we", columnspan=2
        )
        tk.Button(frm, text="List", command=self.on_list).grid(
            row=0, column=3, padx=(6, 0)
        )
        self.btn_connect = tk.Button(frm, text="Connect", command=self.on_connect)
        self.btn_connect.grid(row=0, column=4, padx=(6, 0))
        self.btn_disconnect = tk.Button(
            frm, text="Disconnect", command=self.on_disconnect, state="disabled"
        )
        self.btn_disconnect.grid(row=0, column=5, padx=(6, 0))

        # Timing
        tk.Label(frm, text="Frequency (Hz):").grid(row=1, column=0, sticky="w")
        self.freq_var = tk.StringVar(value="1000")
        # Place frequency entry and period hint side-by-side in a subframe to keep them together
        freq_frame = tk.Frame(frm)
        freq_frame.grid(row=1, column=1, sticky="w")
        tk.Entry(freq_frame, textvariable=self.freq_var, width=12).pack(side=tk.LEFT)
        self.period_hint_var = tk.StringVar(value="Period: —")
        tk.Label(freq_frame, textvariable=self.period_hint_var).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        tk.Label(frm, text="Pulse width (s or SI):").grid(row=1, column=2, sticky="e")
        self.width_var = tk.StringVar(value="0.5e-3")
        tk.Entry(frm, textvariable=self.width_var, width=12).grid(
            row=1, column=3, sticky="w"
        )

        # Levels
        tk.Label(frm, text="High (V):").grid(row=2, column=0, sticky="w")
        self.high_var = tk.StringVar(value="0.5")
        tk.Entry(frm, textvariable=self.high_var, width=12).grid(
            row=2, column=1, sticky="w"
        )
        tk.Label(frm, text="Low (V):").grid(row=2, column=2, sticky="e")
        self.low_var = tk.StringVar(value="-0.5")
        tk.Entry(frm, textvariable=self.low_var, width=12).grid(
            row=2, column=3, sticky="w"
        )

        # Load and phase
        tk.Label(frm, text="Load (ohms or INF):").grid(row=3, column=0, sticky="w")
        self.load_var = tk.StringVar(value="INF")
        tk.Entry(frm, textvariable=self.load_var, width=12).grid(
            row=3, column=1, sticky="w"
        )
        tk.Label(frm, text="Phase (deg):").grid(row=3, column=2, sticky="e")
        self.phase_var = tk.StringVar(value="0")
        tk.Entry(frm, textvariable=self.phase_var, width=12).grid(
            row=3, column=3, sticky="w"
        )

        # Edges (rise/fall) accept seconds or SI (e.g., 10ns, 2.5us, 10e-9)
        tk.Label(frm, text="Lead edge (s or SI):").grid(row=4, column=0, sticky="w")
        self.lead_ns_var = tk.StringVar(value="")  # leave blank to keep current
        tk.Entry(frm, textvariable=self.lead_ns_var, width=12).grid(
            row=4, column=1, sticky="w"
        )
        tk.Label(frm, text="Trail edge (s or SI):").grid(row=4, column=2, sticky="e")
        self.trail_ns_var = tk.StringVar(value="")
        tk.Entry(frm, textvariable=self.trail_ns_var, width=12).grid(
            row=4, column=3, sticky="w"
        )
        # Edge mode selector (Both vs Separate)
        tk.Label(frm, text="Edge mode:").grid(row=4, column=4, sticky="e")
        self.edge_mode_var = tk.StringVar(value="Both")
        tk.OptionMenu(frm, self.edge_mode_var, "Both", "Separate").grid(
            row=4, column=5, sticky="w"
        )

        # Buttons
        btns = tk.Frame(root)
        btns.pack(padx=12, pady=(0, 8), fill=tk.X)
        tk.Button(btns, text="Apply Config", command=self.on_apply).pack(side=tk.LEFT)
        tk.Button(
            btns, text="Output ON", command=lambda: self.safe_run(self.output_on)
        ).pack(side=tk.LEFT, padx=6)
        tk.Button(
            btns, text="Output OFF", command=lambda: self.safe_run(self.output_off)
        ).pack(side=tk.LEFT)
        tk.Button(
            btns, text="Query", command=lambda: self.safe_run(self.query_status)
        ).pack(side=tk.LEFT, padx=6)
        tk.Button(
            btns, text="Status Window", command=self.open_status_window
        ).pack(side=tk.LEFT)
        tk.Button(
            btns, text="Errors", command=lambda: self.safe_run(self.drain_errors)
        ).pack(side=tk.LEFT)
        tk.Button(btns, text="Error Window", command=self.open_error_window).pack(
            side=tk.LEFT, padx=6
        )

        status_frame = tk.Frame(root)
        status_frame.pack(padx=12, pady=(0, 6), fill=tk.X)
        self.status_var = tk.StringVar(value="Disconnected")
        tk.Label(status_frame, textvariable=self.status_var, anchor="w").pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )

        self.log = scrolledtext.ScrolledText(root, width=84, height=16, state="disabled")
        self.log.pack(padx=12, pady=(0, 12), fill=tk.BOTH, expand=True)

        self.status_snapshot = "No status captured yet."
        self.status_win = None
        self.status_text = None

        for i in range(6):
            frm.grid_columnconfigure(i, weight=1)

        # Update period hint initially and on frequency changes
        try:
            self.freq_var.trace_add("write", lambda *_: self._update_period_hint())
        except Exception:
            # Older Tk versions
            self.freq_var.trace("w", lambda *_: self._update_period_hint())
        self._update_period_hint()

    def log_print(self, *args):
        msg = " ".join(str(a) for a in args)
        self.log.configure(state="normal")
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)
        self.log.configure(state="disabled")

    def safe_run(self, func):
        # run instrument actions in a thread to keep UI responsive
        th = threading.Thread(target=self._safe_wrapper, args=(func,))
        th.daemon = True
        th.start()

    def _safe_wrapper(self, func):
        try:
            func()
        except Exception as e:
            self.log_print("Error:", e)

    # --- Status window management ---
    def open_status_window(self):
        if getattr(self, "status_win", None) and tk.Toplevel.winfo_exists(self.status_win):
            self.status_win.deiconify()
            self.status_win.lift()
            self.refresh_status_window()
            return
        self.status_win = tk.Toplevel(self.root)
        self.status_win.title("Instrument Status")
        try:
            x = self.root.winfo_rootx() - 10
            y = self.root.winfo_rooty()
            self.status_win.geometry(f"+{x}+{y}")
        except Exception:
            pass

        frame = tk.Frame(self.status_win)
        frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.status_text = scrolledtext.ScrolledText(frame, width=60, height=18, state="disabled")
        self.status_text.pack(fill=tk.BOTH, expand=True)

        controls = tk.Frame(self.status_win)
        controls.pack(fill=tk.X, padx=8, pady=(0, 8))
        tk.Button(controls, text="Refresh View", command=self.refresh_status_window).pack(
            side=tk.LEFT
        )
        tk.Button(
            controls, text="Query Instrument", command=lambda: self.safe_run(self.query_status)
        ).pack(side=tk.LEFT, padx=6)

        def _on_close():
            try:
                if getattr(self, "status_win", None):
                    self.status_win.destroy()
            finally:
                self.status_win = None
                self.status_text = None

        self.status_win.protocol("WM_DELETE_WINDOW", _on_close)
        self.refresh_status_window()

    def refresh_status_window(self):
        if not getattr(self, "status_text", None):
            return
        self.status_text.configure(state="normal")
        self.status_text.delete("1.0", tk.END)
        self.status_text.insert(tk.END, self.status_snapshot)
        self.status_text.configure(state="disabled")

    def _update_status_snapshot(self, lines):
        if isinstance(lines, (list, tuple)):
            snapshot = "\n".join(str(item) for item in lines)
        else:
            snapshot = str(lines)
        self.status_snapshot = snapshot

        if getattr(self, "status_text", None):
            def _refresh():
                if self.status_text:
                    self.status_text.configure(state="normal")
                    self.status_text.delete("1.0", tk.END)
                    self.status_text.insert(tk.END, self.status_snapshot)
                    self.status_text.configure(state="disabled")

            try:
                self.root.after(0, _refresh)
            except Exception:
                _refresh()

    # --- Error window management ---
    def open_error_window(self):
        if getattr(self, "err_win", None) and tk.Toplevel.winfo_exists(self.err_win):
            self.err_win.deiconify()
            self.err_win.lift()
            return
        self.err_win = tk.Toplevel(self.root)
        self.err_win.title("Instrument Errors")
        # place next to main window
        try:
            x = self.root.winfo_rootx() + self.root.winfo_width() + 10
            y = self.root.winfo_rooty()
            self.err_win.geometry(f"+{x}+{y}")
        except Exception:
            pass

        top = tk.Frame(self.err_win)
        top.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.err_text = scrolledtext.ScrolledText(
            top, width=60, height=20, state="normal"
        )
        self.err_text.pack(fill=tk.BOTH, expand=True)

        controls = tk.Frame(self.err_win)
        controls.pack(fill=tk.X, padx=8, pady=(0, 8))
        tk.Button(controls, text="Refresh", command=self.refresh_error_window).pack(
            side=tk.LEFT
        )
        tk.Button(controls, text="Clear", command=self.clear_error_window).pack(
            side=tk.LEFT, padx=6
        )

        def _on_close():
            try:
                if getattr(self, "err_win", None):
                    self.err_win.destroy()
            finally:
                self.err_win = None
                self.err_text = None

        self.err_win.protocol("WM_DELETE_WINDOW", _on_close)

        # initial load
        self.refresh_error_window()

    def refresh_error_window(self):
        if not getattr(self, "err_text", None):
            return
        try:
            self._require_inst()
            lines = []
            for _ in range(16):
                err = self.inst.query("SYST:ERR?").strip()
                lines.append(err)
                if err.startswith("0,"):
                    break
            # append to error window
            self.err_text.insert(tk.END, "\n".join(lines) + "\n")
            self.err_text.see(tk.END)
        except Exception as e:
            messagebox.showerror("Error Window", str(e))

    def clear_error_window(self):
        if getattr(self, "err_text", None):
            self.err_text.delete("1.0", tk.END)

    @staticmethod
    def _parse_time_to_seconds(text: str) -> float:
        """Parse a time string like '1s', '2.5ms', '10us', '10µs', '3ns', '500ps' -> seconds.
        If unit omitted, assume seconds. Raises ValueError on invalid input."""
        t = text.strip().lower().replace(" ", "")
        if not t:
            raise ValueError("Empty time value")
        # map supported suffixes to multipliers
        units = {
            "s": 1.0,
            "ms": 1e-3,
            "us": 1e-6,
            "µs": 1e-6,
            "ns": 1e-9,
            "ps": 1e-12,
        }
        # try to find a unit suffix
        for u in sorted(units.keys(), key=len, reverse=True):
            if t.endswith(u):
                num = float(t[: -len(u)])
                return num * units[u]
        # no unit -> seconds
        return float(t)

    @staticmethod
    def _format_seconds_si(seconds: float) -> str:
        try:
            s = float(seconds)
        except Exception:
            return "—"
        if s <= 0 or not (s < 1e99):
            return "—"
        # Choose SI unit
        if s >= 1:
            return f"{s:g} s"
        elif s >= 1e-3:
            return f"{s*1e3:g} ms"
        elif s >= 1e-6:
            return f"{s*1e6:g} µs"
        elif s >= 1e-9:
            return f"{s*1e9:g} ns"
        else:
            return f"{s*1e12:g} ps"

    def _update_period_hint(self):
        txt = self.freq_var.get().strip()
        try:
            f = float(txt)
            if f > 0:
                period = 1.0 / f
                self.period_hint_var.set(f"Period ≈ {self._format_seconds_si(period)}")
            else:
                self.period_hint_var.set("Period: —")
        except Exception:
            self.period_hint_var.set("Period: —")

    def on_list(self):
        try:
            if self.rm is None:
                self.rm = pyvisa.ResourceManager()
            res = self.rm.list_resources()
            if not res:
                self.log_print("No instruments found.")
            else:
                self.log_print("Instruments:", ", ".join(res))
        except Exception as e:
            self.log_print("List error:", e)

    def on_connect(self):
        addr = self.addr_var.get().strip()
        try:
            if self.rm is None:
                self.rm = pyvisa.ResourceManager()
            if self.inst is not None:
                try:
                    self.inst.close()
                except Exception:
                    pass
                self.inst = None
            self.inst = self.rm.open_resource(addr)
            self.inst.read_termination = "\n"
            self.inst.write_termination = "\n"
            self.inst.timeout = 10000
            idn = self.inst.query("*IDN?").strip()
            self.log_print("Connected:", idn)
            # perform clean reset like in scripts
            self.inst.clear()
            self.inst.write("*CLS")
            self.inst.write("*RST")
            time.sleep(0.8)
            self.connected = True
            self.status_var.set(f"Connected: {idn}")
            self.btn_connect.configure(state="disabled")
            self.btn_disconnect.configure(state="normal")
            self._update_status_snapshot(f"Connected to {idn}. No configuration applied yet.")
        except Exception as e:
            self.log_print("Connect error:", e)
            self.connected = False
            self.status_var.set("Disconnected")
            self.btn_connect.configure(state="normal")
            self.btn_disconnect.configure(state="disabled")
            self._update_status_snapshot("Disconnected. No status available.")

    def _require_inst(self):
        if self.inst is None:
            raise RuntimeError("Not connected. Click Connect first.")

    def _set_load(self, load_str: str):
        self._require_inst()
        load = load_str.strip().upper()
        if load == "INF" or load == "INFINITE" or load == "HIGHZ" or load == "HZ":
            self.inst.write(f"{OUTPUT}:LOAD INF")
            self.log_print("Load set to INF (High-Z)")
        else:
            try:
                val = float(load)
                if val <= 0:
                    raise ValueError("Load must be > 0")
                self.inst.write(f"{OUTPUT}:LOAD {val}")
                self.log_print(f"Load set to {val} ohms")
            except ValueError:
                raise RuntimeError("Invalid load. Use INF or a positive number (ohms).")

    def on_apply(self):
        self.safe_run(self._apply_inner)

    def _apply_inner(self):
        self._require_inst()
        try:
            # Turn off output during configuration
            self.inst.write(f"{OUTPUT} OFF")
            time.sleep(0.1)  # Small delay to ensure the command is registered

            # Parse inputs
            freq = float(self.freq_var.get().strip())
            if freq <= 0:
                raise RuntimeError("Frequency must be > 0")
            period_s = 1.0 / freq
            width_s = self._parse_time_to_seconds(self.width_var.get())
            high_v = float(self.high_var.get().strip())
            low_v = float(self.low_var.get().strip())
            phase = float(self.phase_var.get().strip())
            lead_ns_txt = self.lead_ns_var.get().strip()
            trail_ns_txt = self.trail_ns_var.get().strip()

            if not (0 < width_s < period_s):
                raise RuntimeError("Pulse width must be > 0 and < period")

            # Set load first
            self._set_load(self.load_var.get())

            # Configure for PULSE using explicit headers
            self.inst.write(f"{SOURCE}:FUNCtion PULSe")
            time.sleep(0.1)  # Ensure the function is set before proceeding
            self.inst.write(f"{PULSE}:PERiod {period_s}")
            self.inst.write(f"{PULSE}:WIDTh {width_s}")
            self.inst.write(f"{SOURCE}:VOLTage:HIGH {high_v}")
            self.inst.write(f"{SOURCE}:VOLTage:LOW {low_v}")
            self.inst.write(f"{SOURCE}:PHASe {phase}")

            # Transition times: set using correct headers
            mode = self.edge_mode_var.get().strip().lower()
            if mode == "separate":
                if lead_ns_txt:
                    lead_s = self._parse_time_to_seconds(lead_ns_txt)
                    if lead_s < 0:
                        raise RuntimeError("Lead edge time must be >= 0")
                    self.inst.write(f"{PULSE}:TRANsition:LEADing {lead_s}")
                if trail_ns_txt:
                    trail_s = self._parse_time_to_seconds(trail_ns_txt)
                    if trail_s < 0:
                        raise RuntimeError("Trail edge time must be >= 0")
                    self.inst.write(f"{PULSE}:TRANsition:TRAiling {trail_s}")
            else:
                # In common mode, require equal values or use one for both
                if lead_ns_txt and trail_ns_txt and (lead_ns_txt != trail_ns_txt):
                    raise RuntimeError(
                        "In 'Both' mode, lead and trail must be equal. Enable 'Separate' or make them the same."
                    )
                val_txt = lead_ns_txt or trail_ns_txt
                if val_txt:
                    val_s = self._parse_time_to_seconds(val_txt)
                    if val_s < 0:
                        raise RuntimeError("Edge time must be >= 0")
                    self.inst.write(f"{PULSE}:TRANsition:LEADing {val_s}")
                    self.inst.write(f"{PULSE}:TRANsition:TRAiling {val_s}")

            # Wait for the instrument to complete configuration
            self.inst.query("*OPC?")  # Ensure all commands are processed
            time.sleep(0.1)

            # Readback
            func = self.inst.query(f"{SOURCE}:FUNCtion?").strip()
            per = self.inst.query(f"{PULSE}:PERiod?").strip()
            wid_q = self.inst.query(f"{PULSE}:WIDTh?").strip()
            vhi = self.inst.query(f"{SOURCE}:VOLTage:HIGH?").strip()
            vlo = self.inst.query(f"{SOURCE}:VOLTage:LOW?").strip()
            try:
                lead_q = self.inst.query(f"{PULSE}:TRANsition:LEADing?").strip()
            except Exception:
                lead_q = "(n/a)"
            try:
                trail_q = self.inst.query(f"{PULSE}:TRANsition:TRAiling?").strip()
            except Exception:
                trail_q = "(n/a)"
            load = self.inst.query(f"{OUTPUT}:LOAD?").strip()
            outp = self.inst.query(f"{OUTPUT}?").strip()

            status_lines = [
                "Applied configuration:",
                f"  Function: {func}",
                f"  Period: {per} s (target {period_s:.6g})",
                f"  Width: {wid_q} s",
                f"  HIGH: {vhi} V  LOW: {vlo} V",
                f"  Lead edge: {lead_q} s  Trail edge: {trail_q} s",
                f"  Load: {load}",
                f"  {OUTPUT}: {outp}",
            ]
            for line in status_lines:
                self.log_print(line)
            self._update_status_snapshot(status_lines)
        except Exception as e:
            self.log_print("Apply error:", e)

    def output_on(self):
        self._require_inst()
        self.inst.write(f"{OUTPUT} ON")
        self.log_print("Output ON")

    def output_off(self):
        self._require_inst()
        self.inst.write(f"{OUTPUT} OFF")
        self.log_print("Output OFF")

    def query_status(self):
        self._require_inst()
        try:
            func = self.inst.query(f"{SOURCE}:FUNCtion?").strip()
            per = self.inst.query(f"{PULSE}:PERiod?").strip()
            wid_q = self.inst.query(f"{PULSE}:WIDTh?").strip()
            vhi = self.inst.query(f"{SOURCE}:VOLTage:HIGH?").strip()
            vlo = self.inst.query(f"{SOURCE}:VOLTage:LOW?").strip()
            try:
                lead_q = self.inst.query(f"{PULSE}:TRANsition:LEADing?").strip()
            except Exception:
                lead_q = "(n/a)"
            try:
                trail_q = self.inst.query(f"{PULSE}:TRANsition:TRAiling?").strip()
            except Exception:
                trail_q = "(n/a)"
            load = self.inst.query(f"{OUTPUT}:LOAD?").strip()
            outp = self.inst.query(f"{OUTPUT}?").strip()
            status_lines = [
                "Status query:",
                f"  Function: {func}",
                f"  Period: {per} s",
                f"  Width: {wid_q} s",
                f"  HIGH: {vhi} V  LOW: {vlo} V",
                f"  Lead edge: {lead_q} s  Trail edge: {trail_q} s",
                f"  Load: {load}",
                f"  {OUTPUT}: {outp}",
            ]
            for line in status_lines:
                self.log_print(line)
            self._update_status_snapshot(status_lines)
        except Exception as e:
            self.log_print("Query error:", e)

    def drain_errors(self):
        self._require_inst()
        for _ in range(8):
            err = self.inst.query("SYST:ERR?")
            self.log_print("[ERR]", err.strip())
            if err.startswith("0,"):
                break

    def close(self):
        try:
            if self.inst is not None:
                try:
                    self.inst.write(f"{OUTPUT} OFF")
                except Exception:
                    pass
                try:
                    self.inst.close()
                except Exception:
                    pass
                self.inst = None
                self.connected = False
        finally:
            try:
                if self.rm is not None:
                    self.rm.close()
            except Exception:
                pass

    def on_disconnect(self):
        try:
            if self.inst is not None:
                try:
                    # Turn output off before disconnecting
                    self.inst.write(f"{OUTPUT} OFF")
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
            self._update_status_snapshot("Disconnected. No active configuration.")
        except Exception as e:
            messagebox.showerror("Disconnection Error", str(e))

    # --- Helpers for transition mode ---
    # Transition mode helpers removed: 33522B accepts LEADing/TRAiling directly without an explicit MODE command


if __name__ == "__main__":
    root = tk.Tk()
    app = PulseGui(root)

    def on_close():
        try:
            app.close()
        finally:
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
