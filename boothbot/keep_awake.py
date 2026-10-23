"""Keeps Windows from sleeping or turning the screen off while BoothBot is open - an unattended
booth gets no mouse/keyboard input between guests, so its idle timers would otherwise run out
mid-event (taking the remote monitor and any background uploads down with it).

SetThreadExecutionState rather than changing the power plan: no admin rights, and nothing to undo -
Windows drops the request the moment the process exits, even on a crash, so the PC's own sleep and
screen-off settings are never touched and apply again as soon as BoothBot closes. It can't stop
power-plan actions like closing a laptop lid or pressing the power button.

The request is held on a thread of its own because execution state is per-thread, and each call on
a thread replaces that thread's previous request. pygame/SDL makes its own display request on the
main thread when it initialises (its default screensaver suppression), and drops it again whenever
the screensaver is allowed - either would silently replace one made there. On a separate thread the
two are independent; BoothApp switches SDL's off along with this one (set_allow_screensaver)."""
import ctypes
import sys
import threading

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

if sys.platform == "win32":
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.SetThreadExecutionState.argtypes = [ctypes.c_uint]
    kernel32.SetThreadExecutionState.restype = ctypes.c_uint
else:  # the booth is Windows-only; keep importable elsewhere
    kernel32 = None

_stop = None  # threading.Event of the thread currently holding the request, if any


def is_supported() -> bool:
    return kernel32 is not None


def set_enabled(enabled: bool) -> None:
    """Starts or ends the keep-awake request; does nothing if it's already in that state. Only
    ever called from the main thread (main() and setup's Tk callbacks), so _stop needs no lock."""
    global _stop
    if kernel32 is None:
        return
    if enabled and _stop is None:
        _stop = threading.Event()
        threading.Thread(target=_hold, args=(_stop,), daemon=True, name="keep-awake").start()
    elif not enabled and _stop is not None:
        _stop.set()
        _stop = None


def _hold(stop):
    if not kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED):
        print("Could not ask Windows to stay awake - it may still sleep or turn the screen off.")
    stop.wait()
    # Exiting the thread would drop the request anyway - clear it explicitly rather than rely on that.
    kernel32.SetThreadExecutionState(ES_CONTINUOUS)
