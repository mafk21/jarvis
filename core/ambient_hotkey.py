"""One-shot Silent Ask shortcut with a system-wide Windows implementation."""
from __future__ import annotations

import platform
import threading
from typing import Callable

DEFAULT_CHORD = ("alt", "shift", "s")
_VK = {"alt": 0x12, "shift": 0x10, "ctrl": 0x11, "s": 0x53}


class SilentAskHotkey:
    def __init__(self, callback: Callable[[], None], chord=DEFAULT_CHORD):
        self.callback = callback
        self.chord = tuple(chord)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.scope = "unavailable"

    def start(self) -> str:
        self.stop()
        self._stop.clear()
        if platform.system() != "Windows" or any(k not in _VK for k in self.chord):
            self.scope = "window"
            return self.scope
        try:
            import ctypes
            ctypes.windll.user32.GetAsyncKeyState
        except Exception:
            self.scope = "window"
            return self.scope
        self.scope = "global"
        self._thread = threading.Thread(target=self._loop, name="silent-ask-hotkey", daemon=True)
        self._thread.start()
        return self.scope

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    def _loop(self) -> None:
        import ctypes
        user32 = ctypes.windll.user32
        was_down = False
        while not self._stop.is_set():
            try:
                down = all(user32.GetAsyncKeyState(_VK[k]) & 0x8000 for k in self.chord)
            except Exception:
                self.scope = "window"
                return
            if down and not was_down:
                try:
                    self.callback()
                except Exception:
                    pass
            was_down = down
            self._stop.wait(1 / 30)
