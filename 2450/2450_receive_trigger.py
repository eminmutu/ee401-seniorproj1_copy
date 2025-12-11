"""
This script provides a Tkinter-based graphical user interface (GUI) for interacting
with a Keithley 2450 SourceMeter. It allows a user to configure and wait for a
digital I/O (DIGIO) trigger from the instrument.

The application loads a Test Script Processor (TSP) script onto the 2450,
which handles the low-level trigger waiting logic on the instrument itself.
The GUI provides controls to connect to the instrument, configure the trigger
parameters (line, edge, mode), and initiate the wait process.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import pyvisa

# --- Constants for GUI and Instrument Configuration ---

# Default VISA address for the instrument.
DEFAULT_ADDRESS = "TCPIP0::169.254.188.69::5025::SOCKET"
# The name for the TSP script that will be loaded onto the instrument.
SCRIPT_NAME = "ReceiveTrigger"
# Options for the trigger edge detection.
EDGE_OPTIONS = ("falling", "rising", "either")
# Available DIGIO line numbers on the 2450.
LINE_NUMBER_OPTIONS = ("1", "2", "3", "4", "5", "6")
# Choices for configuring the DIGIO line mode, mapping user-friendly labels to TSP keys.
LINE_MODE_CHOICES = (
    ("Trigger control, input", "trigger_in"),
    ("Trigger control, open-drain", "trigger_open_drain"),
    ("Trigger control, output", "trigger_out"),
    ("Digital control, input", "digital_in"),
    ("Digital control, output", "digital_out"),
    ("Digital control, open-drain", "digital_open_drain"),
    ("Synchronous master", "synchronous_master"),
    ("Synchronous acceptor", "synchronous_acceptor"),
)
# Labels for the line mode dropdown in the GUI.
LINE_MODE_LABELS = tuple(label for label, _ in LINE_MODE_CHOICES)
# Lookup dictionary to convert GUI labels back to TSP keys.
LINE_MODE_LOOKUP = {label: key for label, key in LINE_MODE_CHOICES}
# Default values for the GUI controls.
DEFAULT_LINE_LABEL = LINE_NUMBER_OPTIONS[0]
DEFAULT_MODE_LABEL = LINE_MODE_CHOICES[0][0]

# --- TSP Script ---
# This multi-line string contains the entire TSP script that will be loaded onto the 2450.
# The script includes functions for setting up the trigger, waiting for it,
# displaying messages on the instrument screen, and handling cancellation.
# It's designed to be self-contained and managed by the Python GUI.
TSP_SCRIPT = """
loadscript {name}
local receive_trigger_cancel_flag = false

function receive_trigger_display_hello()
    display.changescreen(display.SCREEN_USER_SWIPE)
    display.settext(display.TEXT1, "Hello")
    display.settext(display.TEXT2, "")
end

function receive_trigger_display_hey()
    display.changescreen(display.SCREEN_USER_SWIPE)
    display.settext(display.TEXT1, "Hey")
    display.settext(display.TEXT2, "")
end

function receive_trigger_cancel()
    receive_trigger_cancel_flag = true
end

local DEFAULT_EDGE = "falling"
local EDGE_MAP = {{
    rising = trigger.EDGE_RISING,
    falling = trigger.EDGE_FALLING,
    either = trigger.EDGE_EITHER
}}
local DEFAULT_LINE = 1
local DEFAULT_MODE = "trigger_in"
local MODE_MAP = {{
    digital_in = digio.MODE_DIGITAL_IN,
    digital_out = digio.MODE_DIGITAL_OUT,
    digital_open_drain = digio.MODE_DIGITAL_OPEN_DRAIN,
    trigger_in = digio.MODE_TRIGGER_IN,
    trigger_out = digio.MODE_TRIGGER_OUT,
    trigger_open_drain = digio.MODE_TRIGGER_OPEN_DRAIN,
    synchronous_master = digio.MODE_SYNCHRONOUS_MASTER,
    synchronous_acceptor = digio.MODE_SYNCHRONOUS_ACCEPTOR
}}

local function resolve_edge(edge_name)
    if edge_name == nil then
        return EDGE_MAP[DEFAULT_EDGE], DEFAULT_EDGE
    end
    local name = string.lower(tostring(edge_name))
    local edge = EDGE_MAP[name]
    if edge == nil then
        return EDGE_MAP[DEFAULT_EDGE], DEFAULT_EDGE
    end
    return edge, name
end

local function normalize_mode_key(mode_name)
    if mode_name == nil then
        return DEFAULT_MODE
    end
    local key = string.lower(tostring(mode_name))
    key = string.gsub(key, "%s+", "_")
    return key
end

local function resolve_mode(mode_name)
    local key = normalize_mode_key(mode_name)
    local mode = MODE_MAP[key]
    if mode == nil then
        return MODE_MAP[DEFAULT_MODE], DEFAULT_MODE
    end
    return mode, key
end

local function resolve_line(line_number)
    local idx = tonumber(line_number)
    if idx == nil then
        idx = DEFAULT_LINE
    end
    if idx < 1 then
        idx = 1
    elseif idx > 6 then
        idx = 6
    end
    return math.floor(idx + 0.0001)
end

local function is_trigger_input_mode(mode_value)
    return mode_value == digio.MODE_TRIGGER_IN or mode_value == digio.MODE_TRIGGER_OPEN_DRAIN
end

local function ensure_line(line_number, edge, mode_value)
    digio.line[line_number].mode = mode_value
    if is_trigger_input_mode(mode_value) then
        trigger.digin[line_number].edge = edge
        trigger.digin[line_number].clear()
    end
end

function receive_trigger_setup(edge_name, line_number, mode_name)
    local edge, edge_label = resolve_edge(edge_name)
    local mode_value, mode_label = resolve_mode(mode_name)
    local line = resolve_line(line_number)
    ensure_line(line, edge, mode_value)
    receive_trigger_cancel_flag = false
    display.changescreen(display.SCREEN_USER_SWIPE)
    display.settext(display.TEXT1, "Waiting for trigger")
    local text2 = string.format("DIGIO%d (%s, %s)", line, edge_label, mode_label)
    display.settext(display.TEXT2, text2)
end

function receive_trigger_wait(timeout, edge_name, line_number, mode_name)
    local edge, edge_label = resolve_edge(edge_name)
    local mode_value, mode_label = resolve_mode(mode_name)
    local line = resolve_line(line_number)
    ensure_line(line, edge, mode_value)
    receive_trigger_cancel_flag = false
    display.changescreen(display.SCREEN_USER_SWIPE)
    local info = string.format("DIGIO%d (%s, %s)", line, edge_label, mode_label)
    display.settext(display.TEXT1, "Waiting for trigger")
    display.settext(display.TEXT2, info)

    if not is_trigger_input_mode(mode_value) then
        display.settext(display.TEXT1, "Mode not trigger input")
        display.settext(display.TEXT2, info)
        return "INVALID_MODE"
    end

    local triggered = false
    local elapsed = 0
    local chunk = 0.25

    while not triggered and not receive_trigger_cancel_flag do
        local wait_time = chunk
        if timeout ~= nil then
            if timeout <= elapsed then
                break
            end
            if elapsed + wait_time > timeout then
                wait_time = timeout - elapsed
            end
        end
        if wait_time <= 0 then
            break
        end
        triggered = trigger.digin[line].wait(wait_time)
        if timeout ~= nil then
            elapsed = elapsed + wait_time
        end
    end

    if receive_trigger_cancel_flag then
        display.settext(display.TEXT1, "Cancelled")
        display.settext(display.TEXT2, "")
        return "CANCEL"
    elseif triggered then
        display.settext(display.TEXT1, "trig received")
        display.settext(display.TEXT2, "")
        return "TRIGGER"
    else
        display.settext(display.TEXT1, "No trigger (timeout)")
        display.settext(display.TEXT2, "")
        return "TIMEOUT"
    end
end

function receive_trigger_clear_display()
    display.changescreen(display.SCREEN_USER_SWIPE)
    display.settext(display.TEXT1, "")
    display.settext(display.TEXT2, "")
end
endscript
""".format(name=SCRIPT_NAME)


# The main class for the GUI application.
class ReceiveTriggerGUI:
    """Manages the GUI, instrument communication, and trigger waiting process."""

    def __init__(self, root: tk.Misc, *, owns_root: bool = True) -> None:
        self.root = root
        self._owns_root = owns_root
        if isinstance(root, (tk.Tk, tk.Toplevel)):
            self._window = root
        else:
            self._window = root.winfo_toplevel()
        if self._owns_root:
            self._window.title("2450 DIGIO Trigger Listener")
            self._window.minsize(640, 420)

        # VISA and instrument state variables
        self.rm: pyvisa.ResourceManager | None = None
        self.inst: pyvisa.resources.MessageBasedResource | None = None
        self.script_loaded = False

        # Tkinter control variables for UI widgets
        self.address_var = tk.StringVar(value=DEFAULT_ADDRESS)
        self.edge_var = tk.StringVar(value=EDGE_OPTIONS[0])
        self.line_number_var = tk.StringVar(value=DEFAULT_LINE_LABEL)
        self.line_mode_var = tk.StringVar(value=DEFAULT_MODE_LABEL)
        self.timeout_var = tk.StringVar(value="")

        # Threading and state management for the non-blocking wait operation
        self.wait_thread: threading.Thread | None = None
        self.waiting = False
        self.cancel_requested = False
        self.wait_context: dict[str, str] | None = None

        self._build_ui()
        if self._owns_root and hasattr(self._window, "protocol"):
            self._window.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------------ UI --
    # Builds the main user interface for the application.
    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.grid(column=0, row=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        for col in range(6):
            frame.columnconfigure(col, weight=1 if col not in (0, 5) else 0)

        # VISA Address and Connection buttons
        ttk.Label(frame, text="VISA address:").grid(column=0, row=0, sticky="w")
        ttk.Entry(frame, textvariable=self.address_var, width=45).grid(
            column=1, row=0, columnspan=3, sticky="we", padx=(4, 8)
        )
        ttk.Button(frame, text="Connect", command=self.connect).grid(column=4, row=0)
        ttk.Button(frame, text="Disconnect", command=self.disconnect).grid(column=5, row=0, padx=(6, 0))

        # Trigger configuration options
        ttk.Label(frame, text="Edge:").grid(column=0, row=1, sticky="w", pady=(12, 0))
        edge_combo = ttk.Combobox(frame, textvariable=self.edge_var, values=EDGE_OPTIONS, state="readonly", width=12)
        edge_combo.grid(column=1, row=1, sticky="w", pady=(12, 0))

        ttk.Label(frame, text="DIGIO line:").grid(column=0, row=2, sticky="w", pady=(6, 0))
        line_combo = ttk.Combobox(
            frame, textvariable=self.line_number_var, values=LINE_NUMBER_OPTIONS, state="readonly", width=6
        )
        line_combo.grid(column=1, row=2, sticky="w", pady=(6, 0))

        ttk.Label(frame, text="Line mode:").grid(column=0, row=3, sticky="w", pady=(6, 0))
        mode_combo = ttk.Combobox(
            frame, textvariable=self.line_mode_var, values=LINE_MODE_LABELS, state="readonly", width=32
        )
        mode_combo.grid(column=1, row=3, columnspan=3, sticky="w", pady=(6, 0))

        ttk.Label(frame, text="Timeout (s, blank = indefinite):").grid(column=0, row=4, sticky="w")
        ttk.Entry(frame, textvariable=self.timeout_var, width=12).grid(column=1, row=4, sticky="w")

        # Action buttons
        button_row = ttk.Frame(frame)
        button_row.grid(column=0, row=5, columnspan=6, pady=(12, 0), sticky="we")
        for col in range(6):
            button_row.columnconfigure(col, weight=1)

        self.btn_setup = ttk.Button(button_row, text="Setup (show waiting message)", command=self.setup_trigger, state="disabled")
        self.btn_setup.grid(column=0, row=0, padx=4)
        self.btn_wait = ttk.Button(button_row, text="Wait for Trigger", command=self.start_wait, state="disabled")
        self.btn_wait.grid(column=1, row=0, padx=4)
        self.btn_cancel = ttk.Button(button_row, text="Cancel Wait", command=self.cancel_wait, state="disabled")
        self.btn_cancel.grid(column=2, row=0, padx=4)
        self.btn_hello = ttk.Button(button_row, text="Hello", command=self.display_hello, state="disabled")
        self.btn_hello.grid(column=3, row=0, padx=4)
        self.btn_hey = ttk.Button(button_row, text="Hey", command=self.display_hey, state="disabled")
        self.btn_hey.grid(column=4, row=0, padx=4)
        self.btn_clear = ttk.Button(button_row, text="Clear", command=self.clear_display, state="disabled")
        self.btn_clear.grid(column=5, row=0, padx=4)

        self.btn_refresh_errors = ttk.Button(button_row, text="Error Window", command=self.open_error_window)
        self.btn_refresh_errors.grid(column=0, row=1, columnspan=6, pady=(8, 0))

        # Log display area
        log_frame = ttk.LabelFrame(frame, text="Log")
        log_frame.grid(column=0, row=6, columnspan=6, sticky="nsew", pady=(12, 0))
        frame.rowconfigure(6, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=12, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Status bar at the bottom
        status_frame = ttk.Frame(self.root)
        status_frame.grid(column=0, row=1, sticky="we", padx=12, pady=(0, 12))
        self.status_var = tk.StringVar(value="Disconnected")
        ttk.Label(status_frame, textvariable=self.status_var, anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Variables for the separate error window
        self.err_win: tk.Toplevel | None = None
        self.err_text: scrolledtext.ScrolledText | None = None

        self._set_buttons(False, False)

    # ----------------------------------------------------------- Instrument --
    # Establishes a VISA connection to the instrument.
    def connect(self) -> None:
        address = self.address_var.get().strip()
        if not address:
            messagebox.showerror("Connect", "Please provide a VISA address.")
            return
        try:
            # Open the resource and configure communication parameters.
            if self.rm is None:
                self.rm = pyvisa.ResourceManager()
            self.inst = self.rm.open_resource(address)
            self.inst.read_termination = "\n"
            self.inst.write_termination = "\n"
            self.inst.timeout = 20000
            idn = self.inst.query("*IDN?").strip()
            self._log(f"Connected: {idn}")
            self.status_var.set(f"Connected to {idn}")
            # Load the TSP script onto the instrument.
            self._load_script()
            self._set_buttons(True, False)
        except pyvisa.VisaIOError as exc:
            messagebox.showerror("Connect", f"Connection failed: {exc}")
            self._log(f"Connection failed: {exc}")
            self.inst = None
            self._set_buttons(False, False)

    # Disconnects from the instrument and cleans up resources.
    def disconnect(self) -> None:
        # If a wait operation is in progress, try to abort it.
        if self.waiting and self.inst:
            try:
                self.inst.write("abort")
            except pyvisa.VisaIOError:
                pass
        self.waiting = False
        self.wait_context = None
        # Close the instrument and resource manager sessions.
        if self.inst is not None:
            try:
                self.inst.close()
            except pyvisa.VisaIOError:
                pass
        if self.rm is not None:
            try:
                self.rm.close()
            except pyvisa.VisaIOError:
                pass
        self.rm = None
        self.inst = None
        self.script_loaded = False
        self._log("Disconnected.")
        self.status_var.set("Disconnected")
        self._set_buttons(False, False)

    # Loads the TSP script onto the instrument.
    def _load_script(self) -> None:
        if self.inst is None:
            return
        try:
            # First, delete any existing script with the same name.
            self.inst.write(f"pcall(script.delete, '{SCRIPT_NAME}')")
        except pyvisa.VisaIOError:
            # Ignore error if script doesn't exist.
            pass
        try:
            for line in TSP_SCRIPT.strip().splitlines():
                self.inst.write(line)
            self.inst.write(f"{SCRIPT_NAME}.save()")
            self.inst.write(f"{SCRIPT_NAME}()")
            self.script_loaded = True
            self._log("TSP script loaded.")
        except pyvisa.VisaIOError as exc:
            self.script_loaded = False
            messagebox.showerror("Script", f"Failed to load script: {exc}")
            self._log(f"Script load failed: {exc}")

    # ------------------------------------------------------------- Actions --
    # Sends a command to the instrument to display a "waiting" message on its screen.
    def setup_trigger(self) -> None:
        if not self._check_ready():
            return
        edge = self.edge_var.get().strip().lower()
        try:
            line_number = self._resolve_line_number()
            mode_key, mode_label = self._resolve_mode_selection()
        except ValueError as exc:
            messagebox.showerror("Setup", str(exc))
            return

        edge_arg = f"'{edge}'" if edge else "nil"
        try:
            cmd = f"receive_trigger_setup({edge_arg}, {line_number}, '{mode_key}')"
            self.inst.write(cmd)
            self._log(
                f"Setup complete. DIGIO{line_number} configured for {mode_label} mode (edge={edge or 'default'})."
            )
        except pyvisa.VisaIOError as exc:
            messagebox.showerror("Setup", f"Setup failed: {exc}")
            self._log(f"Setup failed: {exc}")

    # Starts the process of waiting for a trigger.
    def start_wait(self) -> None:
        if not self._check_ready():
            return
        if self.waiting:
            messagebox.showinfo("Wait", "Already waiting for a trigger.")
            return

        try:
            timeout_arg = self._format_timeout_arg()
        except ValueError as exc:
            messagebox.showerror("Wait", str(exc))
            return

        edge = self.edge_var.get().strip().lower()

        try:
            line_number = self._resolve_line_number()
            mode_key, mode_label = self._resolve_mode_selection()
        except ValueError as exc:
            messagebox.showerror("Wait", str(exc))
            return

        self.waiting = True
        self.cancel_requested = False
        self.wait_context = {
            "line": str(line_number),
            "mode_label": mode_label,
            "edge": edge or "default",
            "timeout": timeout_arg,
        }
        self._set_buttons(True, True)
        self._log(
            f"Waiting for trigger on DIGIO{line_number} ({mode_label}, edge={edge or 'default'}, timeout={timeout_arg})."
        )

        # Start a new thread to perform the blocking wait operation,
        # so the GUI remains responsive.
        self.wait_thread = threading.Thread(
            target=self._wait_worker, args=(timeout_arg, edge, line_number, mode_key), daemon=True
        )
        self.wait_thread.start()

    # This function runs in a separate thread to wait for the instrument's response.
    def _wait_worker(self, timeout_expr: str, edge: str, line_number: int, mode_key: str) -> None:
        assert self.inst is not None
        edge_arg = f"'{edge}'" if edge else "nil"
        cmd = f"print(receive_trigger_wait({timeout_expr}, {edge_arg}, {line_number}, '{mode_key}'))"
        try:
            response = self.inst.query(cmd).strip().upper()
        except pyvisa.VisaIOError as exc:
            self._async_complete_wait(result=None, error=str(exc))
            return

        # Schedule the completion handler to run on the main GUI thread.
        self._async_complete_wait(result=response)

    # This function is called on the main GUI thread to process the result of the wait operation.
    def _async_complete_wait(self, result: str | None = None, error: str | None = None) -> None:
        def finish() -> None:
            self.waiting = False
            self._set_buttons(True, False)

            handled = False
            res = result.upper() if isinstance(result, str) else None
            context_desc = self._describe_wait_context()

            # Handle different outcomes: cancellation, trigger received, timeout, etc.
            if res == "CANCEL" or (self.cancel_requested and res is None and error is None):
                self._log(f"Wait cancelled for {context_desc}.")
                self.status_var.set("Wait cancelled.")
                handled = True
            elif res == "TRIGGER":
                self._log(f"Trigger received on {context_desc}.")
                self.status_var.set("Trigger received.")
                handled = True
            elif res == "TIMEOUT":
                self._log(f"Timeout waiting on {context_desc}.")
                self.status_var.set("Timeout (no trigger detected).")
                handled = True
            elif res == "INVALID_MODE":
                self._log("Wait aborted: selected line mode is not configured as a trigger input.")
                self.status_var.set("Line mode incompatible with trigger wait.")
                handled = True

            if error and not handled:
                if self.cancel_requested:
                    self._log("Wait cancelled.")
                    self.status_var.set("Wait cancelled.")
                    handled = True
                else:
                    self._log(f"Wait failed: {error}")
                    messagebox.showerror("Wait", f"Trigger wait failed: {error}")
                    handled = True

            if not handled and res and res not in {"CANCEL", "TRIGGER", "TIMEOUT"}:
                self._log(f"Wait result: {result}")
                self.status_var.set(f"Wait result: {result}")

            self.cancel_requested = False
            self.wait_context = None

        self.root.after(0, finish)

    # Sends a command to the instrument to cancel the current wait operation.
    def cancel_wait(self) -> None:
        if not self.waiting or self.inst is None:
            return
        self.cancel_requested = True
        try:
            self.inst.write("receive_trigger_cancel()")
            self._log(f"Cancel requested for {self._describe_wait_context()}.")
        except pyvisa.VisaIOError as exc:
            self.cancel_requested = False
            self._log(f"Cancel wait failed: {exc}")

    # Sends a command to clear the instrument's user display.
    def clear_display(self) -> None:
        if not self._check_ready():
            return
        try:
            self.inst.write("receive_trigger_clear_display()")
            self._log("Display cleared.")
        except pyvisa.VisaIOError as exc:
            self._log(f"Clear display failed: {exc}")

    # Sends a command to display "Hello" on the instrument's screen.
    def display_hello(self) -> None:
        if not self._check_ready():
            return
        try:
            self.inst.write("receive_trigger_display_hello()")
            self._log("Display set to 'Hello'.")
        except pyvisa.VisaIOError as exc:
            self._log(f"Display hello failed: {exc}")

    # Sends a command to display "Hey" on the instrument's screen.
    def display_hey(self) -> None:
        if not self._check_ready():
            return
        try:
            self.inst.write("receive_trigger_display_hey()")
            self._log("Display set to 'Hey'.")
        except pyvisa.VisaIOError as exc:
            self._log(f"Display hey failed: {exc}")

    # Parses the timeout value from the GUI entry.
    def _format_timeout_arg(self) -> str:
        text = self.timeout_var.get().strip()
        if not text:
            return "nil"
        try:
            value = float(text)
        except ValueError as exc:
            raise ValueError("Timeout must be numeric.") from exc
        if value < 0:
            raise ValueError("Timeout must be >= 0.")
        return f"{value}"

    # Parses the DIGIO line number from the GUI combobox.
    def _resolve_line_number(self) -> int:
        value = self.line_number_var.get().strip() or DEFAULT_LINE_LABEL
        try:
            number = int(value)
        except ValueError as exc:
            raise ValueError("Select a valid DIGIO line (1-6).") from exc
        if not 1 <= number <= 6:
            raise ValueError("DIGIO line must be between 1 and 6.")
        return number

    # Parses the line mode from the GUI combobox.
    def _resolve_mode_selection(self) -> tuple[str, str]:
        label = self.line_mode_var.get()
        key = LINE_MODE_LOOKUP.get(label)
        if not key:
            raise ValueError("Select a valid line mode.")
        return key, label

    # Checks if the instrument is connected and the script is loaded.
    def _check_ready(self) -> bool:
        if self.inst is None:
            messagebox.showwarning("Instrument", "Connect to the instrument first.")
            return False
        if not self.script_loaded:
            self._load_script()
            if not self.script_loaded:
                return False
        return True

    # ------------------------------------------------------------- Logging --
    # Appends a message to the log text widget.
    def _log(self, message: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _set_buttons(self, connected: bool, waiting: bool) -> None:
        """Enable or disable GUI buttons based on the application's state."""
        setup_state = "normal" if connected and not waiting else "disabled"
        wait_state = "normal" if connected and not waiting else "disabled"
        cancel_state = "normal" if connected and waiting else "disabled"
        clear_state = "normal" if connected else "disabled"

        self.btn_setup.configure(state=setup_state)
        self.btn_wait.configure(state=wait_state)
        self.btn_cancel.configure(state=cancel_state)
        self.btn_hello.configure(state=clear_state)
        self.btn_hey.configure(state=clear_state)
        self.btn_clear.configure(state=clear_state)

    # Creates a descriptive string for the current wait operation for logging.
    def _describe_wait_context(self) -> str:
        if not self.wait_context:
            return "the selected DIGIO line"
        line = self.wait_context.get("line", "?")
        mode_label = self.wait_context.get("mode_label", "unknown mode")
        return f"DIGIO{line} ({mode_label})"

    # ---------------------------------------------------------- Error view --
    # Opens a separate window to display errors from the instrument.
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

        self.err_text = scrolledtext.ScrolledText(frame, width=60, height=18, state=tk.NORMAL)
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

    # Queries the instrument's error queue and displays the errors in the error window.
    def refresh_errors(self) -> None:
        if self.err_text is None:
            return
        if self.inst is None:
            messagebox.showerror("Errors", "Instrument is not connected.")
            return
        try:
            lines: list[str] = []
            for _ in range(16):
                err = self.inst.query("SYST:ERR?").strip()
                lines.append(err)
                if err.startswith("0,"):
                    break
            self.err_text.insert(tk.END, "\n".join(lines) + "\n")
            self.err_text.see(tk.END)
        except pyvisa.VisaIOError as exc:
            messagebox.showerror("Errors", f"Failed to read errors: {exc}")

    # Clears the text in the error window.
    def clear_error_window(self) -> None:
        if self.err_text:
            self.err_text.delete("1.0", tk.END)

    # --------------------------------------------------------------- Close --
    # Handles the main window closing event.
    def on_close(self) -> None:
        self.disconnect()
        if self._owns_root:
            try:
                self._window.destroy()
            except tk.TclError:
                pass


# Main function to create and run the GUI application.
def main() -> None:
    root = tk.Tk()
    ReceiveTriggerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
