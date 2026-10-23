"""Start-at-sign-in: an entry under the current user's Run registry key that launches BoothBot
with AUTOSTART_ARG, which skips setup and goes straight into the photobooth (see app.main).

The per-user Run key rather than Task Scheduler or a service: no admin rights needed, it's the
same list Task Manager's "Startup apps" page shows (so it can be switched off there too), and it
runs inside the signed-in user's desktop session, which a fullscreen window needs. It fires at
sign-in, not at power-on - an unattended booth also needs Windows' automatic sign-in, which is a
Windows account setting left to the operator."""
import os
import sys
from pathlib import Path

AUTOSTART_ARG = "--autostart"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "BoothBot"

if sys.platform == "win32":
    import winreg
else:  # the booth is Windows-only; keep importable elsewhere
    winreg = None


def is_supported() -> bool:
    return winreg is not None


def launch_command() -> str:
    """The command that starts this copy of BoothBot - the exe itself when packaged, or
    pythonw.exe (no console window) running run.py from source."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" {AUTOSTART_ARG}'
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    run_py = Path(__file__).resolve().parent.parent / "run.py"
    return f'"{pythonw if pythonw.exists() else python}" "{run_py}" {AUTOSTART_ARG}'


def registered_command():
    """The command currently registered to start at sign-in, or None if there isn't one."""
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return value
    except FileNotFoundError:
        return None


def is_enabled() -> bool:
    """True only if *this* copy is registered - a different exe path registered by another copy
    (e.g. an older build in another folder) doesn't count."""
    registered = registered_command()
    return registered is not None and os.path.normcase(registered) == os.path.normcase(launch_command())


def set_enabled(enabled: bool) -> None:
    """Registers (or removes) this copy to start at sign-in. Raises OSError on failure."""
    if winreg is None:
        raise OSError("Starting at sign-in is only supported on Windows")
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
