from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Callable

import tkinter as tk
from tkinter import messagebox, ttk

IV_TSP_PATH = Path(__file__).resolve().with_name("test_2450_iv_multiple.tsp")
if not IV_TSP_PATH.exists():
    raise FileNotFoundError(f"Cannot locate required TSP script: {IV_TSP_PATH}")

# Point the IV sweep GUI at the project-specific TSP script.
def _load_local_module(alias: str, filename: str) -> ModuleType:
    module_path = Path(__file__).resolve().with_name(filename)
    if not module_path.exists():
        raise FileNotFoundError(f"Cannot locate dependency: {module_path}")
    spec = importlib.util.spec_from_file_location(alias, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


trigger_module = _load_local_module("trigger_module", "2450_receive_trigger.py")
iv_module = _load_local_module("iv_module", "2450_gui_iv_multiple.py")

iv_module.TSP_PATH = IV_TSP_PATH


class TriggerReceiveGUI(trigger_module.ReceiveTriggerGUI):
    """Trigger GUI that can raise callbacks when a trigger arrives."""

    def __init__(
        self,
        root: tk.Misc,
        on_trigger: Callable[[], None],
    ) -> None:
        self._trigger_callback = on_trigger
        self._instrument_locked = False
        self._status_before_lock: str | None = None
        super().__init__(root, owns_root=False)

    def _guard_if_locked(self, action: str) -> bool:
        if not self._instrument_locked:
            return True
        messagebox.showinfo("Instrument Busy", f"Cannot {action} while an I-V sweep is running.")
        return False

    def set_instrument_lock(self, locked: bool) -> None:
        if locked == self._instrument_locked:
            return
        self._instrument_locked = locked
        if locked:
            self._status_before_lock = self.status_var.get()
            self.status_var.set("Instrument busy running I-V sweep.")
        else:
            if self._status_before_lock:
                self.status_var.set(self._status_before_lock)
            else:
                self.status_var.set("Trigger operations unlocked.")
            self._status_before_lock = None

    def start_wait(self) -> None:
        if not self._guard_if_locked("start a new wait"):
            return
        super().start_wait()

    def setup_trigger(self) -> None:
        if not self._guard_if_locked("configure the trigger"):
            return
        super().setup_trigger()

    def disconnect(self) -> None:
        if not self._guard_if_locked("disconnect"):
            return
        super().disconnect()

    def _async_complete_wait(self, result: str | None = None, error: str | None = None) -> None:
        triggered = isinstance(result, str) and result.upper() == "TRIGGER"
        super()._async_complete_wait(result=result, error=error)
        if triggered and self._trigger_callback:
            self.root.after(0, self._trigger_callback)


class IntegratedIVSweepApp(iv_module.IVSweepApp):
    """IV sweep GUI that can borrow the trigger GUI's instrument session."""

    def __init__(self, root: tk.Misc) -> None:
        super().__init__(root, owns_root=False)
        self.using_shared_session = False
        self.run_state_callback: Callable[[bool], None] | None = None

    def attach_shared_instrument(
        self,
        instrument,
        resource_manager,
        address: str | None = None,
    ) -> None:
        if self.is_sweep_running():
            raise RuntimeError("Cannot attach a new instrument while a sweep is running.")
        self.inst = instrument
        self.rm = resource_manager
        self.script_loaded = False
        self.using_shared_session = True
        if address:
            self.address_var.set(address)
        self.connect_button.configure(state=tk.DISABLED)
        self.disconnect_button.configure(state=tk.DISABLED)
        self.run_button.configure(state=tk.NORMAL)
        self.log("Using shared instrument session from the trigger window.")

    def release_shared_instrument(self) -> None:
        if not self.using_shared_session:
            return
        self.log("Releasing shared instrument session back to the trigger window.")
        self.inst = None
        self.rm = None
        self.script_loaded = False
        self.using_shared_session = False
        self.run_button.configure(state=tk.DISABLED)
        self.save_button.configure(state=tk.DISABLED)
        self.connect_button.configure(state=tk.NORMAL)
        self.disconnect_button.configure(state=tk.DISABLED)

    def disconnect_instrument(self) -> None:
        if self.using_shared_session:
            self.log("Instrument session is owned by the trigger window; disconnect skipped.")
            return
        super().disconnect_instrument()

    def is_sweep_running(self) -> bool:
        return bool(self.sweep_thread and self.sweep_thread.is_alive())

    def start_sweep(self) -> None:
        super().start_sweep()
        if self.is_sweep_running():
            self._notify_run_state(True)

    def _on_sweep_complete(self, entries: list[dict]) -> None:
        super()._on_sweep_complete(entries)
        self._notify_run_state(False)
        if self.using_shared_session:
            self.release_shared_instrument()

    def _on_sweep_failed(self, error: Exception) -> None:
        super()._on_sweep_failed(error)
        self._notify_run_state(False)
        if self.using_shared_session:
            self.release_shared_instrument()

    def force_close(self, confirm: bool = True, *, destroy_plot: bool = False) -> None:
        if confirm and self.is_sweep_running():
            proceed = messagebox.askyesno(
                "Stop I-V Sweep",
                "A sweep is still running. Stop it?",
                icon="warning",
            )
            if not proceed:
                return
        self._stop_and_cleanup(destroy_plot=destroy_plot)

    def _notify_run_state(self, running: bool) -> None:
        if self.run_state_callback:
            self.run_state_callback(running)

    def _stop_and_cleanup(self, destroy_plot: bool = False) -> None:
        self.stop_event.set()
        if self.sweep_thread and self.sweep_thread.is_alive():
            self.sweep_thread.join(timeout=2.0)
        if self.using_shared_session:
            self.release_shared_instrument()
        else:
            super().disconnect_instrument()
        if destroy_plot:
            iv_module.plt.close(self.figure)
        self._notify_run_state(False)


class ReceiveAndIVApp:
    """Top-level application that hosts the trigger and I-V sweep GUIs in one window."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("2450 Trigger Listener + I-V Sweep")
        self.root.minsize(1100, 720)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.trigger_tab = ttk.Frame(self.notebook)
        self.iv_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.trigger_tab, text="Trigger Wait")
        self.notebook.add(self.iv_tab, text="I-V Sweep")

        self.trigger_gui = TriggerReceiveGUI(
            self.trigger_tab,
            on_trigger=self._handle_trigger,
        )
        self.iv_app = IntegratedIVSweepApp(self.iv_tab)
        self.iv_app.run_state_callback = self._on_iv_run_state_changed

        self.root.protocol("WM_DELETE_WINDOW", self._handle_root_close)

    def _focus_iv_tab(self) -> None:
        self.notebook.select(self.iv_tab)

    def _handle_trigger(self) -> None:
        if self.iv_app.is_sweep_running():
            messagebox.showinfo(
                "Trigger",
                "An I-V sweep is already running. The new trigger is ignored.",
            )
            return
        if self.trigger_gui.inst is None:
            messagebox.showwarning(
                "Trigger",
                "Trigger detected but the instrument is disconnected. Connect and wait again.",
            )
            return
        self._focus_iv_tab()
        self.iv_app.attach_shared_instrument(
            self.trigger_gui.inst,
            self.trigger_gui.rm,
            address=self.trigger_gui.address_var.get(),
        )
        self.trigger_gui.set_instrument_lock(True)
        self.iv_app.start_sweep()
        if not self.iv_app.is_sweep_running():
            self.iv_app.release_shared_instrument()
            self.trigger_gui.set_instrument_lock(False)

    def _on_iv_run_state_changed(self, running: bool) -> None:
        self.trigger_gui.set_instrument_lock(running)

    def _handle_root_close(self) -> None:
        if self.iv_app:
            self.iv_app.force_close(confirm=False, destroy_plot=True)
        self.trigger_gui.on_close()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    ReceiveAndIVApp().run()


if __name__ == "__main__":
    main()
