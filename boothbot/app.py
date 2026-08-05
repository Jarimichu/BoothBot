"""Fullscreen kiosk photobooth: start page -> live preview -> countdown -> capture -> upload."""
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pygame

from . import __version__, capture_log, uploader
from .camera import Camera, CameraError
from .monitor_server import MonitorServer

START = "start"
LIVE = "live"
COUNTDOWN = "countdown"
FLASH = "flash"
REVIEW = "review"

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
MONITOR_URL_COLOR = (90, 90, 90)
FLASH_DURATION_S = 0.15
LIVE_IDLE_TIMEOUT_S = 30
SCALED_REVIEW_PHOTO_RATIO = 0.75
CAMERA_HEALTH_INTERVAL_S = 5
UPLOAD_RETRY_WINDOW_S = 15 * 60
UPLOAD_RETRY_INTERVAL_S = 60


def frame_to_surface(frame_rgb):
    height, width, _ = frame_rgb.shape
    return pygame.image.frombuffer(frame_rgb.tobytes(), (width, height), "RGB")


def scale_to_fit(surface, target_size):
    target_w, target_h = target_size
    src_w, src_h = surface.get_size()
    scale = min(target_w / src_w, target_h / src_h)
    new_size = (max(1, int(src_w * scale)), max(1, int(src_h * scale)))
    scaled = pygame.transform.smoothscale(surface, new_size)
    offset = ((target_w - new_size[0]) // 2, (target_h - new_size[1]) // 2)
    return scaled, offset


class BoothApp:
    def __init__(self, config):
        self.config = config

        pygame.init()
        pygame.display.set_caption(f"BoothBot v{__version__}")
        flags = pygame.FULLSCREEN if config.fullscreen else 0
        self.screen = pygame.display.set_mode((0, 0) if config.fullscreen else (1280, 720), flags)
        self.screen_size = self.screen.get_size()

        self.font_big = pygame.font.SysFont("Arial", 220, bold=True)
        self.font_med = pygame.font.SysFont("Arial", 64, bold=True)
        self.font_small = pygame.font.SysFont("Arial", 36)
        self.font_tiny = pygame.font.SysFont("Arial", 20)

        try:
            self.capture_key = pygame.key.key_code(config.capture_key)
        except ValueError:
            print(f"Unknown capture_key '{config.capture_key}', defaulting to space")
            self.capture_key = pygame.K_SPACE
        try:
            self.quit_key = pygame.key.key_code(config.quit_key)
        except ValueError:
            self.quit_key = pygame.K_ESCAPE

        self.camera = Camera(config.camera_index)
        self.clock = pygame.time.Clock()

        self.start_logo_surface = self._load_start_logo()

        self.state = START
        self.state_entered_at = time.time()
        self.countdown_start = None
        self.captured_frame = None

        # Live status, read by the monitor server's handler thread via _status_snapshot(), and
        # written by both the main thread (state/camera/last_capture_at) and potentially several
        # concurrent background retry threads (failure counters/last_error/last_success_at) - up
        # to UPLOAD_RETRY_WINDOW_S/15 minutes can elapse between a capture and its outcome being
        # known, so more than one capture's retry loop can be in flight at once. _status_lock
        # guards every read-modify-write of the failure-tracking fields; everything else is a
        # single atomically-assigned attribute (never split across two reads) so the handler
        # thread can never observe a torn/inconsistent pair even without locking.
        self._status_lock = threading.Lock()
        self.session_started_at = datetime.now()
        self.camera_ok = None
        self.camera_checked_at = None
        self.last_capture_at = None
        self.last_success_at = None
        self.last_error = None  # (datetime, str) | None - sticky, not cleared by a later success
        self.captures_this_session = 0
        self.failures_this_session = 0
        self.consecutive_failures = 0
        self._last_camera_health_check = 0.0

        self.monitor = None
        self.monitor_url = None

    def _load_start_logo(self):
        if not self.config.start_logo_path:
            return None
        logo_path = Path(self.config.start_logo_path)
        if not logo_path.exists():
            print(f"Start logo not found: {logo_path}")
            return None
        try:
            image = pygame.image.load(str(logo_path)).convert_alpha()
        except pygame.error as exc:
            print(f"Could not load start logo '{logo_path}': {exc}")
            return None
        max_box = (int(self.screen_size[0] * 0.5), int(self.screen_size[1] * 0.45))
        scaled, _ = scale_to_fit(image, max_box)
        return scaled

    def run(self):
        """Returns True if the user pressed the quit key (setup should reopen), False if the window
        was closed outright (e.g. Alt+F4), meaning the whole program should exit."""
        if self.config.monitor_enabled:
            self.monitor = MonitorServer(self._status_snapshot, port=self.config.monitor_port)
            self.monitor_url = self.monitor.start()

        running = True
        return_to_setup = False
        try:
            while running:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                    elif event.type == pygame.KEYDOWN:
                        if event.key == self.quit_key:
                            running = False
                            return_to_setup = True
                        elif event.key == self.capture_key and self.state == START:
                            self.state = LIVE
                            self.state_entered_at = time.time()
                        elif event.key == self.capture_key and self.state == LIVE:
                            self._start_countdown()

                self._update()
                self._draw()
                self.clock.tick(30)
        finally:
            if self.monitor is not None:
                self.monitor.stop()
            self.camera.release()
            pygame.quit()
        return return_to_setup

    def _start_countdown(self):
        self.state = COUNTDOWN
        self.countdown_start = time.time()

    def _update(self):
        now = time.time()

        if self.state == START:
            if now - self._last_camera_health_check >= CAMERA_HEALTH_INTERVAL_S:
                self._read_camera_frame()
                self._last_camera_health_check = now

        elif self.state == LIVE:
            if now - self.state_entered_at >= LIVE_IDLE_TIMEOUT_S:
                self.state = START
                self.state_entered_at = now

        elif self.state == COUNTDOWN:
            elapsed = now - self.countdown_start
            remaining = self.config.countdown_seconds - elapsed
            if remaining <= 0:
                self._capture_and_flash()

        elif self.state == FLASH:
            if now - self.state_entered_at >= FLASH_DURATION_S:
                self.state = REVIEW
                self.state_entered_at = now

        elif self.state == REVIEW:
            # The upload (started back at capture time) keeps running in the background regardless
            # of what's on screen - there's no "wait for it" state here anymore. It resolves (and
            # gets logged) whenever it resolves, up to UPLOAD_RETRY_WINDOW_S later.
            if now - self.state_entered_at >= self.config.photo_review_seconds:
                self.state = START
                self.state_entered_at = now

    def _read_camera_frame(self):
        """The only place the camera is read from - tracks live health for the monitor dashboard."""
        frame = self.camera.read_frame_rgb()
        self.camera_ok = frame is not None
        self.camera_checked_at = datetime.now()
        return frame

    def _capture_and_flash(self):
        frame = self._read_camera_frame()
        if frame is not None:
            self.captured_frame = frame
        captured_at = datetime.now()
        self.last_capture_at = captured_at
        self.captures_this_session += 1  # only ever written from the main thread - no lock needed
        self.state = FLASH
        self.state_entered_at = time.time()
        self._start_upload(captured_at)

    def _start_upload(self, captured_at):
        """Saves the photo locally (always, synchronously) and hands off to a background thread that
        posts to whichever destinations are enabled - retrying only the ones still failing, for up to
        UPLOAD_RETRY_WINDOW_S, so a slow/flaky network doesn't produce a false failure in the log.
        Fully detached from the guest-facing state machine: nothing here blocks REVIEW's return to START."""
        if self.captured_frame is None:
            self._finalize_capture(
                photo_path=None, captured_at=captured_at, saved_locally=False,
                results=[uploader.UploadResult("local", False, "Capture failed - no frame from camera")],
                attempts={},
            )
            return

        timestamp = captured_at.strftime("%Y%m%d_%H%M%S")
        photo_path = self.config.photos_dir / f"booth_{timestamp}.jpg"
        try:
            saved_ok = self.camera.save_frame(self.captured_frame, photo_path)
        except Exception as exc:
            print(f"Could not save photo locally: {exc}")
            saved_ok = False

        config = self.config  # a Config instance is never mutated after BoothApp starts - safe to share
        threading.Thread(
            target=self._upload_with_retries,
            args=(photo_path, captured_at, saved_ok, config),
            daemon=True,
        ).start()

    def _upload_with_retries(self, photo_path, captured_at, saved_locally, config):
        """Runs entirely on a background thread. Retries only the destinations that haven't
        succeeded yet (never a destination that already posted - that would duplicate it),
        checking back every UPLOAD_RETRY_INTERVAL_S until everything succeeds, each destination
        hits its own attempt cap (see max_attempts below), or UPLOAD_RETRY_WINDOW_S has passed
        since the photo was taken. Registers itself with capture_log's pending registry while in
        flight, so the Logs tab can show it before it has a captures.csv row."""
        pending = {}
        if config.discord_enabled:
            pending["discord"] = None
        if config.telegram_enabled:
            pending["telegram"] = None

        # Telegram's failure signal is unreliable - a request can time out (or otherwise lose its
        # response) even though the photo was already delivered, see uploader.py - so retrying it
        # on a timer like Discord risks reposting a photo that already went through. Cap its total
        # attempts via config instead (default 0 retries = try once, never resend); Discord keeps
        # retrying purely on the time-based deadline below, since its webhook responses are reliable.
        max_attempts = {"discord": None, "telegram": config.telegram_max_retries + 1}

        attempts = {name: 0 for name in pending}
        last_result = {}
        deadline = time.time() + UPLOAD_RETRY_WINDOW_S
        key = captured_at.isoformat()

        if pending:
            capture_log.register_pending(
                key, photo_file=photo_path.name if photo_path else "", captured_at=captured_at,
                saved_locally=saved_locally, discord_enabled=config.discord_enabled,
                telegram_enabled=config.telegram_enabled,
                deadline_at=captured_at + timedelta(seconds=UPLOAD_RETRY_WINDOW_S),
            )

        try:
            while pending and time.time() < deadline:
                for name in list(pending.keys()):
                    attempts[name] += 1
                    try:
                        if name == "discord":
                            result = uploader.post_to_discord(photo_path, config.discord_webhook_url)
                        else:
                            result = uploader.post_to_telegram(photo_path, config.telegram_bot_token, config.telegram_chat_id)
                    except Exception as exc:
                        # This loop runs unattended for up to UPLOAD_RETRY_WINDOW_S with no supervision -
                        # an unexpected exception here must never kill the thread, or this capture would
                        # never get logged at all (worse than a false-negative failure entry).
                        result = uploader.UploadResult(name, False, f"{name}: unexpected error - {exc}")
                    last_result[name] = result
                    capture_log.update_pending(
                        key, name, attempts=attempts[name], success=result.success, message=result.message
                    )
                    limit = max_attempts[name]
                    if result.success or (limit is not None and attempts[name] >= limit):
                        del pending[name]
                if pending:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        break
                    time.sleep(min(UPLOAD_RETRY_INTERVAL_S, remaining))
        finally:
            capture_log.resolve_pending(key)

        results = list(last_result.values())
        if not results:
            message = "Saved locally" if saved_locally else "Could not save photo locally"
            results = [uploader.UploadResult("local", saved_locally, message)]

        self._finalize_capture(photo_path, captured_at, saved_locally, results, attempts)

    def _finalize_capture(self, photo_path, captured_at, saved_locally, results, attempts):
        """The one place a capture's outcome is fully known - writes the capture log and updates
        live status. May run on the main thread (a failed local save short-circuits here directly)
        or on a background retry thread, possibly minutes after the photo was taken; several of
        these can be in flight concurrently if photos are taken close together, so the
        failure-tracking fields are updated under _status_lock."""
        by_destination = {result.destination: result for result in results}
        discord_result = by_destination.get("discord")
        telegram_result = by_destination.get("telegram")
        resolved_at = datetime.now()

        capture_log.append_capture(
            photo_file=photo_path.name if photo_path else "",
            saved_locally=saved_locally,
            discord_enabled=discord_result is not None,
            discord_success=discord_result.success if discord_result else False,
            discord_message=discord_result.message if discord_result else "",
            discord_attempts=attempts.get("discord", 0),
            telegram_enabled=telegram_result is not None,
            telegram_success=telegram_result.success if telegram_result else False,
            telegram_message=telegram_result.message if telegram_result else "",
            telegram_attempts=attempts.get("telegram", 0),
            captured_at=captured_at,
            resolved_at=resolved_at,
        )

        with self._status_lock:
            all_ok = saved_locally and all(result.success for result in results)
            if all_ok:
                self.last_success_at = resolved_at
                self.consecutive_failures = 0
            else:
                self.failures_this_session += 1
                self.consecutive_failures += 1
                failing = [result.message for result in results if not result.success]
                if not saved_locally:
                    failing.insert(0, "Local save failed")
                self.last_error = (resolved_at, "; ".join(failing) if failing else "Unknown error")

    def _draw(self):
        self.screen.fill(BLACK)

        if self.state == START:
            frame = None
        elif self.state in (FLASH, REVIEW):
            frame = self.captured_frame
        else:
            frame = self._read_camera_frame()

        if frame is not None:
            surface = frame_to_surface(frame)
            if self.config.scale_review_photo and self.state == REVIEW:
                box_w = int(self.screen_size[0] * SCALED_REVIEW_PHOTO_RATIO)
                box_h = int(self.screen_size[1] * SCALED_REVIEW_PHOTO_RATIO)
            else:
                box_w, box_h = self.screen_size
            scaled, offset = scale_to_fit(surface, (box_w, box_h))
            box_origin = ((self.screen_size[0] - box_w) // 2, (self.screen_size[1] - box_h) // 2)
            self.screen.blit(scaled, (box_origin[0] + offset[0], box_origin[1] + offset[1]))

        if self.state == START:
            message_y_ratio = 0.5
            if self.start_logo_surface is not None:
                logo_rect = self.start_logo_surface.get_rect(
                    center=(self.screen_size[0] / 2, self.screen_size[1] * 0.42)
                )
                self.screen.blit(self.start_logo_surface, logo_rect)
                message_y_ratio = 0.78
            self._draw_wrapped_centered_text(self.config.start_message, self.font_med, WHITE, y_ratio=message_y_ratio)
            if self.monitor_url and self.config.monitor_show_url:
                self._draw_monitor_url()

        elif self.state == LIVE:
            self._draw_wrapped_centered_text(self.config.prompt_message, self.font_med, WHITE, y_ratio=0.88)

        elif self.state == COUNTDOWN:
            remaining = self.config.countdown_seconds - (time.time() - self.countdown_start)
            number = max(1, int(remaining) + 1)
            self._draw_centered_text(str(number), self.font_big, WHITE, y_ratio=0.5, shadow=True)

        elif self.state == FLASH:
            self.screen.fill(WHITE)

        elif self.state == REVIEW:
            # Deliberately the last thing guests see - no "Sending..."/"Thank you!" stage after this.
            # The upload (already running in the background) resolves silently; its outcome is only
            # visible to the operator via the Logs tab and remote monitor, not on this screen.
            self._draw_wrapped_centered_text(self.config.review_message_top, self.font_small, WHITE, y_ratio=0.08, shadow=True)
            self._draw_wrapped_centered_text(
                self.config.review_message_bottom, self.font_small, WHITE, y_ratio=0.92, shadow=True
            )

        pygame.display.flip()

    def _draw_monitor_url(self):
        surf = self.font_tiny.render(f"Monitor: {self.monitor_url}", True, MONITOR_URL_COLOR)
        rect = surf.get_rect()
        margin = 12
        rect.bottomleft = (margin, self.screen_size[1] - margin)
        self.screen.blit(surf, rect)

    def _status_snapshot(self):
        """Called from the monitor server's handler thread - must only read plain attributes,
        never touch pygame or the camera."""
        destinations = []
        if self.config.discord_enabled:
            destinations.append("Discord")
        if self.config.telegram_enabled:
            destinations.append("Telegram")
        return {
            "state": self.state,
            "session_started_at": self.session_started_at,
            "camera_ok": self.camera_ok,
            "camera_checked_at": self.camera_checked_at,
            "last_capture_at": self.last_capture_at,
            "last_success_at": self.last_success_at,
            "last_error": self.last_error,
            "captures_this_session": self.captures_this_session,
            "failures_this_session": self.failures_this_session,
            "consecutive_failures": self.consecutive_failures,
            "destinations": destinations,
        }

    def _draw_centered_text(self, text, font, color, y_ratio, shadow=False):
        if shadow:
            shadow_surf = font.render(text, True, BLACK)
            shadow_rect = shadow_surf.get_rect(center=(self.screen_size[0] / 2 + 3, self.screen_size[1] * y_ratio + 3))
            self.screen.blit(shadow_surf, shadow_rect)
        text_surf = font.render(text, True, color)
        text_rect = text_surf.get_rect(center=(self.screen_size[0] / 2, self.screen_size[1] * y_ratio))
        self.screen.blit(text_surf, text_rect)

    def _draw_wrapped_centered_text(self, text, font, color, y_ratio, shadow=False, max_width_ratio=0.85):
        max_width = self.screen_size[0] * max_width_ratio
        words = text.split()
        lines = [words[0]] if words else [""]
        for word in words[1:]:
            candidate = f"{lines[-1]} {word}"
            if font.size(candidate)[0] <= max_width:
                lines[-1] = candidate
            else:
                lines.append(word)

        line_height = font.get_linesize()
        top = self.screen_size[1] * y_ratio - (line_height * len(lines)) / 2
        for i, line in enumerate(lines):
            center_y = top + line_height * i + line_height / 2
            if shadow:
                shadow_surf = font.render(line, True, BLACK)
                shadow_rect = shadow_surf.get_rect(center=(self.screen_size[0] / 2 + 3, center_y + 3))
                self.screen.blit(shadow_surf, shadow_rect)
            text_surf = font.render(line, True, color)
            text_rect = text_surf.get_rect(center=(self.screen_size[0] / 2, center_y))
            self.screen.blit(text_surf, text_rect)


def main():
    from .config import Config, load_config_dict, save_config_dict
    from .setup_ui import SetupWindow

    raw_config = load_config_dict()

    while True:
        setup = SetupWindow(raw_config)
        result = setup.run()
        if result is None:
            print("Setup cancelled - exiting.")
            return

        if setup.remember_settings:
            save_config_dict(result)
        raw_config = result
        config = Config(result)

        try:
            app = BoothApp(config)
        except CameraError as exc:
            print(f"Fatal: {exc}")
            _show_fatal_error(str(exc))
            return

        if not app.run():
            return


def _show_fatal_error(message: str):
    """Surfaces startup failures via a message box too, since packaged --windowed builds have no console."""
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("BoothBot", f"Could not start the photobooth:\n\n{message}")
        root.destroy()
    except Exception:
        pass
