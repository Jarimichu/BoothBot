"""Updates BoothBot from its GitHub releases: checks the latest release, downloads its BoothBot.exe,
and swaps it in for the running one.

Only ever driven from the setup screen, and only installs when the operator clicks - nothing here
runs during the fullscreen booth or an auto-start. When running from source there's no exe to
replace, so setup just shows what's new and links to the release (see can_self_update).

The swap relies on Windows letting a running exe be renamed but not deleted or overwritten: the
running BoothBot.exe is renamed to BoothBot.exe.old, the download takes its name, and the new copy
deletes the .old one once it starts (remove_leftovers). Keeping the same path means the Windows
startup entry (autostart.py) and any shortcuts still point at the right file. The download goes to
the exe's own folder, so the final rename never crosses drives - config.json lives there too, so
it's already known to be writable."""
import ctypes
import hashlib
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import NamedTuple, Optional

import requests

from . import __version__
from .config import ROOT_DIR

GITHUB_REPO = "Jarimichu/BoothBot"
# /releases/latest skips drafts and pre-releases, so publishing one of those never offers it.
LATEST_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
ASSET_NAME = "BoothBot.exe"  # the file each release must have attached - see README's Releases section

CHECK_TIMEOUT = (10, 30)
DOWNLOAD_TIMEOUT = (10, 60)  # per read, not for the whole ~70 MB
DOWNLOAD_CHUNK = 256 * 1024
# Reopening setup (Esc from the booth) reuses the last answer instead of asking GitHub again; the
# Check for Updates button always asks. Unauthenticated API calls are limited to 60 an hour.
CHECK_CACHE_S = 60 * 60

LEFTOVER_RETRY_S = 2
LEFTOVER_ATTEMPTS = 30  # the old copy's bootloader may still be cleaning up as the new one starts

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


class UpdateError(Exception):
    """Something went wrong checking, downloading or installing - the message is shown in setup."""


class UpdateCancelled(Exception):
    pass


class Release(NamedTuple):
    version: tuple
    tag: str
    notes: str
    page_url: str
    asset_url: Optional[str]  # None if the release has no BoothBot.exe attached
    asset_size: int
    sha256: Optional[str]  # from GitHub's asset digest; None if it didn't report one


_cached_check = None  # (time.time(), Release or None) from the last successful check
# Set by install(). The setup screen opens again after every booth session in the same run, and
# this stops it offering (and downloading) the same update twice.
_installed = None


def parse_version(text) -> Optional[tuple]:
    """"v1.10.0" / "1.10.0" -> (1, 10, 0); None for anything else, which is never "newer"."""
    parts = str(text).strip().lstrip("vV").split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def format_version(version: tuple) -> str:
    return "v" + ".".join(str(part) for part in version)


def can_self_update() -> bool:
    """Only a packaged exe can replace itself - from source, the user updates with git."""
    return bool(getattr(sys, "frozen", False))


def _headers():
    return {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"BoothBot/{__version__}",
    }


def check_latest(force=False) -> Optional[Release]:
    """The latest release if it's newer than this one, else None. Raises UpdateError when GitHub
    can't be asked (offline, rate-limited, ...)."""
    global _cached_check
    if not force and _cached_check is not None and time.time() - _cached_check[0] < CHECK_CACHE_S:
        return _cached_check[1]

    try:
        resp = requests.get(LATEST_URL, headers=_headers(), timeout=CHECK_TIMEOUT)
    except requests.RequestException as exc:
        raise UpdateError(f"couldn't reach GitHub ({type(exc).__name__})") from exc
    if resp.status_code == 404:
        raise UpdateError("no releases published yet")
    if resp.status_code in (403, 429):
        raise UpdateError("GitHub's rate limit was reached - try again in a while")
    if resp.status_code != 200:
        raise UpdateError(f"GitHub answered HTTP {resp.status_code}")
    try:
        data = resp.json()
        tag = data["tag_name"]
    except (ValueError, KeyError, TypeError) as exc:
        raise UpdateError("GitHub's answer couldn't be read") from exc

    latest = parse_version(tag)
    current = parse_version(__version__)
    release = None
    if latest is not None and current is not None and latest > current:
        asset = next((a for a in data.get("assets") or [] if a.get("name") == ASSET_NAME), None)
        digest = (asset or {}).get("digest") or ""
        release = Release(
            version=latest,
            tag=tag,
            notes=(data.get("body") or "").strip(),
            page_url=data.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases",
            asset_url=asset.get("browser_download_url") if asset else None,
            asset_size=int(asset.get("size") or 0) if asset else 0,
            sha256=digest[len("sha256:"):].lower() if digest.startswith("sha256:") else None,
        )
    _cached_check = (time.time(), release)
    return release


def _download_path() -> Path:
    return ROOT_DIR / f"{ASSET_NAME}.download"


def download(release: Release, progress, cancel: threading.Event) -> Path:
    """Downloads the release's exe next to the running one and checks it's intact. progress(done,
    total) is called from this (background) thread as bytes arrive. The partial file is deleted on
    any failure or cancel."""
    if not release.asset_url:
        raise UpdateError(f"{release.tag} has no {ASSET_NAME} attached")
    path = _download_path()
    sha256 = hashlib.sha256()
    done = 0
    try:
        with requests.get(release.asset_url, headers=_headers(), stream=True, timeout=DOWNLOAD_TIMEOUT) as resp:
            if resp.status_code != 200:
                raise UpdateError(f"download failed - HTTP {resp.status_code}")
            total = release.asset_size or int(resp.headers.get("Content-Length") or 0)
            with open(path, "wb") as f:
                for chunk in resp.iter_content(DOWNLOAD_CHUNK):
                    if cancel.is_set():
                        raise UpdateCancelled()
                    if done == 0 and not chunk.startswith(b"MZ"):
                        raise UpdateError("the download isn't a Windows program")
                    f.write(chunk)
                    sha256.update(chunk)
                    done += len(chunk)
                    progress(done, total)
        if release.asset_size and done != release.asset_size:
            raise UpdateError(f"download incomplete ({done:,} of {release.asset_size:,} bytes)")
        if release.sha256 and sha256.hexdigest() != release.sha256:
            raise UpdateError("the download doesn't match GitHub's checksum")
    except requests.RequestException as exc:
        _remove_quietly(path)
        raise UpdateError(f"download failed ({type(exc).__name__})") from exc
    except OSError as exc:
        _remove_quietly(path)
        raise UpdateError(f"couldn't save the download ({exc.strerror or exc})") from exc
    except BaseException:
        _remove_quietly(path)
        raise
    return path


def installed_release() -> Optional[Release]:
    """The release install() put in place during this run, which takes over at the next start."""
    return _installed


def install(downloaded: Path, release: Release) -> None:
    """Puts the downloaded exe where the running one is. The running copy keeps running (as .old)
    until it exits. Raises UpdateError, leaving the running exe in place, if it can't."""
    global _installed
    exe = Path(sys.executable)
    old = exe.with_name(f"{exe.name}.old")
    if old.exists() and not _remove_quietly(old):
        # Still locked by a copy that hasn't finished closing - step aside rather than fail.
        old = exe.with_name(f"{exe.name}.old-{int(time.time())}")
    try:
        os.replace(exe, old)
    except OSError as exc:
        raise UpdateError(f"couldn't move the current version aside ({exc.strerror or exc})") from exc
    try:
        os.replace(downloaded, exe)
    except OSError as exc:
        os.replace(old, exe)
        raise UpdateError(f"couldn't put the new version in place ({exc.strerror or exc})") from exc
    _installed = release


def relaunch() -> None:
    """Starts the (just installed) exe as a separate program. Raises OSError if it can't."""
    exe = Path(sys.executable)
    # Otherwise the new exe's bootloader would think it's a child of this one and look for its
    # files in this copy's _MEI temp folder, which is deleted as this copy exits.
    env = {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}
    if sys.platform == "win32":
        # PyInstaller points this process's DLL search path at its _MEI folder; don't pass that on.
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    subprocess.Popen(
        [str(exe)], cwd=str(ROOT_DIR), env=env, close_fds=True,
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
    )


def remove_leftovers() -> None:
    """Deletes the previous version left behind by install() (and any abandoned download), in the
    background - right after an update, the old copy may still hold its file for a few seconds."""
    if not can_self_update():
        return
    exe = Path(sys.executable)

    def leftovers():
        return [*exe.parent.glob(f"{exe.name}.old*"), _download_path()]

    def work():
        for _ in range(LEFTOVER_ATTEMPTS):
            if all(_remove_quietly(path) for path in leftovers()):
                return
            time.sleep(LEFTOVER_RETRY_S)

    threading.Thread(target=work, daemon=True).start()


def _remove_quietly(path: Path) -> bool:
    """True once the file is gone (or never existed)."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        return False
    return True
