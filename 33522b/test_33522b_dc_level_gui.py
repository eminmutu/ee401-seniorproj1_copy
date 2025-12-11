import tkinter as tk
from tkinter import messagebox, scrolledtext
import threading
import time

import pyvisa

DEFAULT_ADDR = "TCPIP0::169.254.5.22::5025::SOCKET"


class DCLevelGui:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("33522B DC Level GUI")

        self.rm = None
        self.inst = None
        self.connected = False
        self.channel = 1

        main = tk.Frame(root)
        main.pack(padx=12, pady=10, fill=tk.X)

        tk.Label(main, text="VISA Address:").grid(row=0, column=0, sticky="w")
        self.addr_var = tk.StringVar(value=DEFAULT_ADDR)
        tk.Entry(main, textvariable=self.addr_var, width=40).grid(
            row=0, column=1, sticky="we", columnspan=2
        )
        tk.Button(main, text="List", command=self.on_list).grid(row=0, column=3, padx=(6, 0))
        self.btn_connect = tk.Button(main, text="Connect", command=self.on_connect)
        self.btn_connect.grid(row=0, column=4, padx=(6, 0))
        self.btn_disconnect = tk.Button(
            main, text="Disconnect", command=self.on_disconnect, state="disabled"
        )
        self.btn_disconnect.grid(row=0, column=5, padx=(6, 0))
        tk.Label(main, text="Channel:").grid(row=0, column=6, sticky="e")
        self.channel_var = tk.StringVar(value="CH1")
        tk.OptionMenu(main, self.channel_var, "CH1", "CH2", command=self.on_channel_select).grid(
            row=0, column=7, sticky="w"
        )

        tk.Label(main, text="DC Level (V):").grid(row=1, column=0, sticky="w")
        self.level_var = tk.StringVar(value="0.5")
        tk.Entry(main, textvariable=self.level_var, width=12).grid(row=1, column=1, sticky="w")

        tk.Label(main, text="Load (ohms or INF):").grid(row=1, column=2, sticky="e")
        self.load_var = tk.StringVar(value="INF")
        tk.Entry(main, textvariable=self.load_var, width=12).grid(row=1, column=3, sticky="w")

        btns = tk.Frame(root)
        btns.pack(padx=12, pady=(0, 8), fill=tk.X)
        tk.Button(btns, text="Apply DC Level", command=self.on_apply).pack(side=tk.LEFT)
        tk.Button(btns, text="Output ON", command=lambda: self.safe_run(self.output_on)).pack(
            side=tk.LEFT, padx=6
        )
        tk.Button(btns, text="Output OFF", command=lambda: self.safe_run(self.output_off)).pack(
            side=tk.LEFT
        )
        tk.Button(btns, text="Query", command=lambda: self.safe_run(self.query_status)).pack(
            side=tk.LEFT, padx=6
        )
        tk.Button(btns, text="Errors", command=lambda: self.safe_run(self.drain_errors)).pack(
            side=tk.LEFT
        )
        tk.Button(btns, text="Error Window", command=self.open_error_window).pack(
            side=tk.LEFT, padx=6
        )

        status_frame = tk.Frame(root)
        status_frame.pack(padx=12, pady=(0, 8), fill=tk.X)
        self.status_var = tk.StringVar(value="Disconnected")
        tk.Label(status_frame, textvariable=self.status_var, anchor="w").pack(side=tk.LEFT)

        self.log = scrolledtext.ScrolledText(root, width=80, height=16, state="disabled")
        self.log.pack(padx=12, pady=(0, 12), fill=tk.BOTH, expand=True)

        for i in range(7):
            main.grid_columnconfigure(i, weight=1)

        self.err_win = None
        self.err_text = None
        self._update_status_channel_suffix()

    def log_print(self, *args):
        msg = " ".join(str(a) for a in args)
        self.log.configure(state="normal")
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)
        self.log.configure(state="disabled")

    def safe_run(self, func):
        th = threading.Thread(target=self._safe_wrapper, args=(func,))
        th.daemon = True
        th.start()

    def _safe_wrapper(self, func):
        try:
            func()
        except Exception as exc:
            self.log_print("Error:", exc)

    def _require_inst(self):
        if self.inst is None:
            raise RuntimeError("Not connected. Click Connect first.")

    def on_list(self):
        try:
            if self.rm is None:
                self.rm = pyvisa.ResourceManager()
            res = self.rm.list_resources()
            if res:
                self.log_print("Instruments:", ", ".join(res))
            else:
                self.log_print("No instruments found.")
        except Exception as exc:
            self.log_print("List error:", exc)

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
            self.inst.timeout = 5000
            idn = self.inst.query("*IDN?").strip()
            self.log_print("Connected:", idn)
            self.inst.clear()
            self.inst.write("*CLS")
            self.inst.write("*RST")
            time.sleep(0.8)
            self.connected = True
            self.status_var.set(f"Connected: {idn}")
            self._update_status_channel_suffix()
            self.btn_connect.configure(state="disabled")
            self.btn_disconnect.configure(state="normal")
        except Exception as exc:
            self.log_print("Connect error:", exc)

    def on_disconnect(self):
        try:
            if self.inst is not None:
                try:
                    self.inst.write(f":OUTP{self.channel} OFF")
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
        except Exception as exc:
            messagebox.showerror("Disconnection Error", str(exc))

    def on_channel_select(self, value):
        self.channel = 1 if value == "CH1" else 2
        self.log_print(f"Active channel -> {value}")
        self._update_status_channel_suffix()

    def _update_status_channel_suffix(self):
        try:
            base = self.status_var.get().split("|")[0].strip()
            if self.connected:
                self.status_var.set(f"{base} | CH{self.channel}")
            else:
                self.status_var.set("Disconnected")
        except Exception:
            pass

    def _set_load(self, load_text: str):
        self._require_inst()
        load = load_text.strip().upper()
        outp_prefix = f":OUTP{self.channel}"
        if load in {"INF", "INFINITE", "HIGHZ", "HZ"}:
            self.inst.write(f"{outp_prefix}:LOAD INF")
            self.log_print("Load set to INF")
        else:
            try:
                value = float(load)
            except ValueError as exc:
                raise RuntimeError("Invalid load. Use INF or positive number.") from exc
            if value <= 0:
                raise RuntimeError("Load must be > 0.")
            self.inst.write(f"{outp_prefix}:LOAD {value}")
            self.log_print(f"Load set to {value} ohms")

    def on_apply(self):
        self.safe_run(self._apply_inner)

    def _apply_inner(self):
        self._require_inst()
        try:
            level = float(self.level_var.get().strip())
            load = self.load_var.get()

            self._set_load(load)

            src = f":SOUR{self.channel}"
            self.inst.write(f"{src}:FUNC DC")
            self.inst.write(f"{src}:VOLT:OFFS {level}")

            func = self.inst.query(f"{src}:FUNC?").strip()
            offs = self.inst.query(f"{src}:VOLT:OFFS?").strip()
            outp_prefix = f":OUTP{self.channel}"
            load_q = self.inst.query(f"{outp_prefix}:LOAD?").strip()
            outp_state = self.inst.query(f"{outp_prefix}?").strip()

            self.log_print("Applied:")
            self.log_print("  Function:", func)
            self.log_print("  DC level:", offs, "V")
            self.log_print("  Load:", load_q)
            self.log_print("  Output state:", outp_state)
        except Exception as exc:
            self.log_print("Apply error:", exc)

    def output_on(self):
        self._require_inst()
        self.inst.write(f":OUTP{self.channel} ON")
        self.log_print(f"CH{self.channel} Output ON")

    def output_off(self):
        self._require_inst()
        self.inst.write(f":OUTP{self.channel} OFF")
        self.log_print(f"CH{self.channel} Output OFF")

    def query_status(self):
        self._require_inst()
        try:
            src = f":SOUR{self.channel}"
            func = self.inst.query(f"{src}:FUNC?").strip()
            offs = self.inst.query(f"{src}:VOLT:OFFS?").strip()
            outp_prefix = f":OUTP{self.channel}"
            load = self.inst.query(f"{outp_prefix}:LOAD?").strip()
            state = self.inst.query(f"{outp_prefix}?").strip()
            self.log_print("Status:")
            self.log_print("  Function:", func)
            self.log_print("  DC level:", offs, "V")
            self.log_print("  Load:", load)
            self.log_print("  Output state:", state)
        except Exception as exc:
            self.log_print("Query error:", exc)

    def drain_errors(self):
        self._require_inst()
        for _ in range(16):
            err = self.inst.query("SYST:ERR?").strip()
            self.log_print("[ERR]", err)
            if err.startswith("0,"):
                break

    def open_error_window(self):
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

        top = tk.Frame(self.err_win)
        top.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.err_text = scrolledtext.ScrolledText(top, width=60, height=20, state="normal")
        self.err_text.pack(fill=tk.BOTH, expand=True)

        controls = tk.Frame(self.err_win)
        controls.pack(fill=tk.X, padx=8, pady=(0, 8))
        tk.Button(controls, text="Refresh", command=self.refresh_error_window).pack(side=tk.LEFT)
        tk.Button(controls, text="Clear", command=self.clear_error_window).pack(side=tk.LEFT, padx=6)

        def _on_close():
            try:
                if self.err_win:
                    self.err_win.destroy()
            finally:
                self.err_win = None
                self.err_text = None

        self.err_win.protocol("WM_DELETE_WINDOW", _on_close)
        self.refresh_error_window()

    def refresh_error_window(self):
        if not self.err_text:
            return
        try:
            self._require_inst()
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

    def clear_error_window(self):
        if self.err_text:
            self.err_text.delete("1.0", tk.END)

    def close(self):
        try:
            if self.inst is not None:
                try:
                    self.inst.write(f":OUTP{self.channel} OFF")
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

    def on_app_close(self):
        try:
            self.close()
        finally:
            self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    gui = DCLevelGui(root)
    root.protocol("WM_DELETE_WINDOW", gui.on_app_close)
    root.mainloop()
