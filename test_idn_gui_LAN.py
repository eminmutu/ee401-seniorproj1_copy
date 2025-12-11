# while this is useful it doesn't see the keysight 33522b
# 33522b was added manually through NI MAX as it didn't see either, however after adding it manually it works...

import tkinter as tk
from tkinter import scrolledtext
import pyvisa


def create_resource_gui(extra_buttons=None):
    rm = pyvisa.ResourceManager()

    # --- GUI callbacks ---
    def log_write(msg):
        txt.insert(tk.END, msg + "\n")
        txt.see(tk.END)

    def refresh_list():
        listbox.delete(0, tk.END)
        try:
            resources = rm.list_resources()
            for r in resources:
                listbox.insert(tk.END, r)
            log_write(f"Number of available resources: {len(resources)}")
        except Exception as e:
            log_write(f"Error listing resources: {e}")

    def send_idn():
        sel = listbox.curselection()
        if not sel:
            log_write("Select a resource first.")
            return
        addr = listbox.get(sel[0])
        # Normalize LAN INSTR to SOCKET form, remove ::inst0
        if addr.startswith("TCPIP") and addr.endswith("INSTR"):
            addr = addr.replace("::inst0", "")
            addr = addr.rsplit("::", 1)[0] + "::5025::SOCKET"
        try:
            inst = rm.open_resource(addr)
            inst.read_termination = "\n"
            inst.write_termination = "\n"
            inst.timeout = 5000
            idn = inst.query("*IDN?")
            log_write(f"Resource: {addr}")
            log_write(f"*IDN? -> {idn.strip()}")
            inst.close()
        except Exception as e:
            log_write(f"Error: {e}")

    def clear_log():
        txt.delete("1.0", tk.END)

    def on_close():
        try:
            rm.close()
        except Exception:
            pass
        root.destroy()

    # --- Root window ---
    root = tk.Tk()
    root.title("VISA Resource Selector & *IDN?")
    root.geometry("900x520")

    frame = tk.Frame(root)
    frame.pack(padx=8, pady=8, fill=tk.BOTH, expand=True)

    listbox = tk.Listbox(frame, height=10, width=100)
    listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scroll = tk.Scrollbar(frame, command=listbox.yview)
    scroll.pack(side=tk.LEFT, fill=tk.Y)
    listbox.config(yscrollcommand=scroll.set)

    btn_frame = tk.Frame(root)
    btn_frame.pack(fill=tk.X, padx=8, pady=(0, 8))

    tk.Button(btn_frame, text="Refresh", command=refresh_list).pack(
        side=tk.LEFT, padx=4
    )
    tk.Button(btn_frame, text="*IDN?", command=send_idn).pack(side=tk.LEFT, padx=4)
    tk.Button(btn_frame, text="Clear Log", command=clear_log).pack(side=tk.LEFT, padx=4)

    # Extra buttons injected from caller (e.g., “Select test”)
    if extra_buttons:
        for label, callback in extra_buttons:
            tk.Button(btn_frame, text=label, command=lambda cb=callback: cb(root)).pack(
                side=tk.LEFT, padx=4
            )

    txt = scrolledtext.ScrolledText(root, height=12, wrap=tk.WORD)
    txt.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

    # Initial population
    refresh_list()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


# Allow running standalone
if __name__ == "__main__":
    create_resource_gui()
