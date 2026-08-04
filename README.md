# BoothBot
**Version 1.2.0** ([changelog](CHANGELOG.md))

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
   - **General**: capture button key / quit key (click the field, then press the actual button/key you want - no need to know its name), the fullscreen toggle, and **Remember these settings for next time** (checked by default) - uncheck it to try something out for this run only without overwriting `config.json`.
   - **Start Page**: the message and optional logo shown fullscreen when the app first launches, before the live camera view (click Browse to pick a PNG/JPG for the logo, Clear to remove it). Pressing the capture button/key here moves on to the live view.
   - **Live View**: the message shown on the TV before a group presses the button, and the countdown length (a dropdown of common values - 3 to 10 seconds - but still editable if you want something else).
   - **Photo Review**: how long the captured photo is shown (dropdown), the top/bottom messages overlaid on it (e.g. "Thanks for coming to the con!" / "Please see your photo on the Telegram channel"), and the "Scale review photo to 75%" checkbox - when checked, the photo shrinks and centers so those messages sit clearly above/below it instead of overlapping.
   - **Result**: how long the send-succeeded/failed message is shown (dropdown).
   - **Discord & Telegram**: webhook URL (Discord channel Settings -> Integrations -> Webhooks), bot token ([@BotFather](https://t.me/BotFather)), and chat ID (`https://api.telegram.org/bot<token>/getUpdates`, or message [@userinfobot](https://t.me/userinfobot) for a personal chat).

   Click **Start Photobooth** to launch the fullscreen booth view (saving these to `config.json` unless you unchecked "Remember these settings"), or **Quit** to exit without starting.

Once fullscreen, press `Esc` (or whichever quit key you configured) to return to the setup screen - adjust settings and click **Start Photobooth** again, or click **Quit** there to close the program entirely.

## How it works

- **Setup screen**: a Tkinter window with a live webcam preview and a form for all booth settings; saves to `config.json` and hands off to the fullscreen view.
- **Start page**: the first thing shown fullscreen - a configurable message and optional logo, no camera feed. Pressing the button moves to the live view.
- **Live view**: shows the webcam feed fullscreen with a "press the button" prompt. Returns to the start page automatically after 30 seconds if no photo is taken.
- **Button press**: starts a countdown (big on-screen numbers).
- **Capture**: grabs a frame, flashes the screen white, and saves the photo to `photos/`. The upload to Discord/Telegram starts immediately in the background.
- **Photo review**: displays the captured photo by itself for the configured number of seconds, while the upload happens behind the scenes.
- **Result**: shows a success/failure message (waiting for the upload to finish first, if it's still in progress) for the configured number of seconds, then returns to the start page.

## Packaging as a standalone .exe

Once you're happy with it, bundle it into a single .exe so the booth PC doesn't need a visible Python install:
```
pip install pyinstaller
pyinstaller BoothBot.spec --distpath .
```
This produces `BoothBot.exe` right in the project root - a single windowed (no console) file, built from the checked-in `BoothBot.spec` (`--distpath .` skips PyInstaller's default `dist/` subfolder). Copy `BoothBot.exe` to wherever you want it on the booth PC and just run it; on first launch it creates `config.json` and a `photos/` folder right next to itself (settings and captures live beside the exe, not in a temp folder, so they persist between runs). Rerun the exe any time to reopen the setup screen and adjust settings.

To have it start automatically when the booth PC boots, put a shortcut to `BoothBot.exe` in the Windows Startup folder (`Win+R` -> `shell:startup`).

If you change the code, rebuild with `pyinstaller BoothBot.spec --distpath .` (edit `BoothBot.spec` directly if you need to change build options like the app name or icon). `BoothBot.exe` is gitignored, same as `build/` - it's a generated artifact, not source.
