# BoothBot
**Version 1.0.2** ([changelog](CHANGELOG.md))

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
   A **setup window** opens first with a live camera preview and editable settings:
   - **Camera index**: usually `0`; bump it up (and click Refresh) if the wrong camera shows up in the preview.
   - **Live view message**: the text shown on the TV before a group presses the button (e.g. "Press the button to take a photo!" or a custom line for your event). Wraps automatically if it's long.
   - **Review message (top) / Review message (bottom)**: smaller text overlaid near the top and bottom of the captured photo while it's shown after the flash, so the photo itself stays the focus (e.g. "Thanks for coming to the con!" / "Please see your photo on the Telegram channel").
   - **Capture button key / Quit key**: click into the field and press the actual button/key you want to use (no need to know its name) - for the USB button, this doubles as a quick test that it registers as a keypress at all.
   - **Countdown / photo review / result display seconds**, **fullscreen toggle**.
   - **Discord webhook URL**: create one under Discord channel Settings -> Integrations -> Webhooks.
   - **Telegram bot token**: message [@BotFather](https://t.me/BotFather) on Telegram to create a bot.
   - **Telegram chat ID**: add the bot to your channel/group and use `https://api.telegram.org/bot<token>/getUpdates` to find the chat id (or message [@userinfobot](https://t.me/userinfobot) for a personal chat).

   Click **Start Photobooth** to save these to `config.json` and launch the fullscreen booth view, or **Quit** to exit without starting.

Once fullscreen, press `Esc` (or whichever quit key you configured) to return to the desktop.

## How it works

- **Setup screen**: a Tkinter window with a live webcam preview and a form for all booth settings; saves to `config.json` and hands off to the fullscreen view.
- **Live view**: shows the webcam feed fullscreen with a "press the button" prompt.
- **Button press**: starts a countdown (big on-screen numbers).
- **Capture**: grabs a frame, flashes the screen white, and saves the photo to `photos/`. The upload to Discord/Telegram starts immediately in the background.
- **Photo review**: displays the captured photo by itself for the configured number of seconds, while the upload happens behind the scenes.
- **Result**: shows a success/failure message (waiting for the upload to finish first, if it's still in progress) for the configured number of seconds, then returns to the live view.

## Packaging as a standalone .exe

Once you're happy with it, bundle it into a single .exe so the booth PC doesn't need a visible Python install:
```
pip install pyinstaller
pyinstaller BoothBot.spec --distpath .
```
This produces `BoothBot.exe` right in the project root - a single windowed (no console) file, built from the checked-in `BoothBot.spec` (`--distpath .` skips PyInstaller's default `dist/` subfolder). Copy `BoothBot.exe` to wherever you want it on the booth PC and just run it; on first launch it creates `config.json` and a `photos/` folder right next to itself (settings and captures live beside the exe, not in a temp folder, so they persist between runs). Rerun the exe any time to reopen the setup screen and adjust settings.

To have it start automatically when the booth PC boots, put a shortcut to `BoothBot.exe` in the Windows Startup folder (`Win+R` -> `shell:startup`).

If you change the code, rebuild with `pyinstaller BoothBot.spec --distpath .` (edit `BoothBot.spec` directly if you need to change build options like the app name or icon). `BoothBot.exe` is gitignored, same as `build/` - it's a generated artifact, not source.
