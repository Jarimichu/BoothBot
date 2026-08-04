# Changelog

All notable changes to BoothBot are documented in this file.

## [1.0.1] - 2026-08-04

### Added
- Configurable "live view message" setting - the prompt text shown fullscreen before a group presses the button is now editable from the setup screen instead of hardcoded, and wraps automatically if it's long.

## [1.0.0] - 2026-08-04

### Added
- Initial release: fullscreen kiosk photobooth - live webcam preview, button-triggered countdown, capture, and automatic upload to Discord (webhook) and/or Telegram (bot).
- Setup screen with a live camera preview and editable settings (camera index, countdown/result timers, capture/quit keys, fullscreen toggle, Discord/Telegram credentials) shown before the fullscreen view launches.
- Packaging as a standalone Windows `.exe` via PyInstaller, including a persistent `config.json`/`photos/` location next to the exe and embedded Windows file-version metadata.
