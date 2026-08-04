# BoothBot
**Version 1.7.2** ([changelog](CHANGELOG.md))

Button-triggered photobooth for events - snaps a photo from a webcam after a countdown and auto-posts it to Telegram/Discord.

## Setup

1. Install [Python 3.10+](https://www.python.org/downloads/) on the Windows PC.
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Plug in the webcam, connect the PC to the TV (extend or duplicate display), and plug in the USB button (it just needs to register as a keyboard key press - no drivers required).
4. Run the app:
   ```
   python run.py
   ```
   A **setup window** opens first with a live camera preview on the left (camera index is a dropdown right below it - pick one and it refreshes automatically) and the rest of the settings organized into tabs on the right:
   - **General**: capture button key / quit key (click the field, then press the actual button/key you want - no need to know its name), the fullscreen toggle, and **Remember these settings for next time** (checked by default) - uncheck it to try something out for this run only without overwriting `config.json`. Below that, **Remote Monitor**: an "Enable remote monitor" checkbox (on by default), the port it listens on, a "Show the monitor URL on the start page" checkbox (off by default - the setup screen is the normal way to find the URL, so guests don't see it), and a preview of the URL with a **Copy** button - see [Remote monitoring](#remote-monitoring) below.
   - **Start Page**: the message and optional logo shown fullscreen when the app first launches, before the live camera view (click Browse to pick a PNG/JPG for the logo, Clear to remove it). Pressing the capture button/key here moves on to the live view.
   - **Live View**: the message shown on the TV before a group presses the button, and the countdown length (a dropdown of common values - 3 to 10 seconds - but still editable if you want something else).
   - **Post View**: how long the captured photo is shown (dropdown), and the top/bottom messages overlaid on it (e.g. "Thanks for coming to the con!" / "Please see your photo on the Telegram channel"), plus the "Scale review photo to 75%" checkbox (checked by default - shrinks and centers the photo so those messages sit clearly above/below it instead of overlapping). The photo review is the last thing guests see - there's no separate "Sending.../Thank you!" screen afterward; the upload happens silently in the background.
   - **Photo Storage**: photos are always saved locally to a `photos/` folder next to the app - click **Open Folder** to see them. Below that, **Post to Discord** and **Post to Telegram** checkboxes (both off by default - turn one on once you've filled in its credentials below) let you enable/disable each destination independently without clearing its saved credentials - webhook URL (Discord channel Settings -> Integrations -> Webhooks), bot token ([@BotFather](https://t.me/BotFather)), and chat ID (`https://api.telegram.org/bot<token>/getUpdates`, or message [@userinfobot](https://t.me/userinfobot) for a personal chat). Each destination has a **Send Test Message** button (enabled once its fields are filled in) that posts a real test message, so you can confirm it actually works before the event starts instead of finding out on the first guest photo.
   - **Logs**: a record of every photo taken, kept in `logs/captures.csv` next to the app (click **Open Folder** to see it) - a bar chart of photo counts by hour of day, color-coded by outcome (delivered / saved locally only / partly delivered / failed), plus a summary of totals and per-destination success/failure counts. Click **Refresh** to pick up photos taken since the tab was last viewed.

   Click **Start Photobooth** to launch the fullscreen booth view (saving these to `config.json` unless you unchecked "Remember these settings"), or **Quit** to exit without starting.

Once fullscreen, press `Esc` (or whichever quit key you configured) to return to the setup screen - adjust settings and click **Start Photobooth** again, or click **Quit** there to close the program entirely.

## How it works

- **Setup screen**: a Tkinter window with a live webcam preview and a form for all booth settings; saves to `config.json` and hands off to the fullscreen view.
- **Start page**: the first thing shown fullscreen - a configurable message and optional logo, no camera feed. Pressing the button moves to the live view.
- **Live view**: shows the webcam feed fullscreen with a "press the button" prompt. Returns to the start page automatically after 30 seconds if no photo is taken.
- **Button press**: starts a countdown (big on-screen numbers).
- **Capture**: grabs a frame, flashes the screen white, and always saves the photo to `photos/` locally. If Discord and/or Telegram are enabled, that upload starts immediately in the background too.
- **Photo review**: displays the captured photo by itself for the configured number of seconds, then returns straight to the start page. This is the last thing guests see - there's no follow-up "Sending.../Thank you!" screen, and the app never reveals upload success or failure to guests. An intermittent network hiccup can make a genuinely successful send look like a failure, which would otherwise be confusing.
- **Background upload retries**: uploading to Discord/Telegram happens entirely on a background thread, decoupled from the guest-facing state machine. If a destination fails, it's retried automatically (only that destination - a destination that already succeeded is never re-sent, so guests never get double-posted) roughly once a minute for up to 15 minutes before giving up. The capture log entry is written only once every destination has either succeeded or the 15-minute window has elapsed, so the log reflects the true final outcome rather than a snapshot taken moments after the shutter. That status is visible to you, the operator, via the Logs tab and the [remote monitor](#remote-monitoring).
- **Capture log**: every photo attempt (successful or not) is appended to `logs/captures.csv` once its outcome is fully resolved - timestamp captured, timestamp resolved, whether it saved locally, and per destination: whether it succeeded, the resulting status message, and how many attempts it took. The setup screen's Logs tab reads this to show the hourly chart.

## Remote monitoring

While the fullscreen booth view is running (not during setup), BoothBot hosts a small read-only web dashboard on the local network - useful for checking on an unattended booth from a phone without walking up to it and interrupting a guest's photo.

- **Reachable only while the booth is live.** The server starts when you click Start Photobooth and stops the moment you return to setup - it's never running otherwise.
- **No login required.** It's open to anyone on the same network, but only shows stats and status (booth state, camera health, recent errors, hourly photo counts) - never photos, webhook URLs, or bot tokens.
- **Finding the URL**: the setup screen's General tab shows it ahead of time, with a Copy button (the LAN IP is knowable before the server even starts). You can also check "Show the monitor URL on the start page" (off by default, so guests at the booth don't see it) to have it appear small and dim in the bottom-left corner of the fullscreen start page as confirmation it started. Auto-refreshes every 10 seconds (a "pause auto-refresh" link is there for reading a long error message without the page jumping).
- **Windows Firewall**: the first time something connects, Windows may prompt to allow BoothBot through the firewall on private networks - allow it, or nothing on your network will be able to load the page.
- Turn it off entirely or change the port via the General tab's Remote Monitor section.

## Packaging as a standalone .exe

Once you're happy with it, bundle it into a single .exe so the booth PC doesn't need a visible Python install:
```
pip install pyinstaller
pyinstaller BoothBot.spec --distpath .
```
This produces `BoothBot.exe` right in the project root - a single windowed (no console) file, built from the checked-in `BoothBot.spec` (`--distpath .` skips PyInstaller's default `dist/` subfolder). Copy `BoothBot.exe` to wherever you want it on the booth PC and just run it; on first launch it creates `config.json`, a `photos/` folder, and a `logs/` folder right next to itself (settings, captures, and the capture log all live beside the exe, not in a temp folder, so they persist between runs). Rerun the exe any time to reopen the setup screen and adjust settings.

To have it start automatically when the booth PC boots, put a shortcut to `BoothBot.exe` in the Windows Startup folder (`Win+R` -> `shell:startup`).

If you change the code, rebuild with `pyinstaller BoothBot.spec --distpath .` (edit `BoothBot.spec` directly if you need to change build options like the app name or icon). `BoothBot.exe` is gitignored, same as `build/` - it's a generated artifact, not source.
