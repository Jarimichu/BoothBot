"""Fullscreen kiosk photobooth: live preview -> countdown -> capture -> upload."""
import queue
import threading
import time
from datetime import datetime

import pygame

from . import __version__, uploader
from .camera import Camera, CameraError

LIVE = "live"
COUNTDOWN = "countdown"
FLASH = "flash"
REVIEW = "review"
UPLOADING = "uploading"
RESULT = "result"

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GREEN = (80, 220, 100)
RED = (230, 70, 70)
FLASH_DURATION_S = 0.15


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
        self.upload_queue = queue.Queue()

        pygame.init()
        pygame.display.set_caption(f"BoothBot v{__version__}")
        flags = pygame.FULLSCREEN if config.fullscreen else 0
        self.screen = pygame.display.set_mode((0, 0) if config.fullscreen else (1280, 720), flags)
        self.screen_size = self.screen.get_size()

        self.font_big = pygame.font.SysFont("Arial", 220, bold=True)
        self.font_med = pygame.font.SysFont("Arial", 64, bold=True)
        self.font_small = pygame.font.SysFont("Arial", 36)

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

        self.state = LIVE
        self.state_entered_at = time.time()
        self.countdown_start = None
        self.captured_frame = None
        self.result_lines = []

    def run(self):
        running = True
        try:
            while running:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                    elif event.type == pygame.KEYDOWN:
                        if event.key == self.quit_key:
                            running = False
                        elif event.key == self.capture_key and self.state == LIVE:
                            self._start_countdown()

                self._update()
                self._draw()
                self.clock.tick(30)
        finally:
            self.camera.release()
            pygame.quit()

    def _start_countdown(self):
        self.state = COUNTDOWN
        self.countdown_start = time.time()

    def _update(self):
        now = time.time()

        if self.state == COUNTDOWN:
            elapsed = now - self.countdown_start
            remaining = self.config.countdown_seconds - elapsed
            if remaining <= 0:
                self._capture_and_flash()

        elif self.state == FLASH:
            if now - self.state_entered_at >= FLASH_DURATION_S:
                self.state = REVIEW
                self.state_entered_at = now

        elif self.state == REVIEW:
            if now - self.state_entered_at >= self.config.photo_review_seconds:
                self._advance_after_review()

        elif self.state == UPLOADING:
            try:
                results = self.upload_queue.get_nowait()
            except queue.Empty:
                pass
            else:
                self.result_lines = [msg for _, msg in results]
                self.state = RESULT
                self.state_entered_at = now

        elif self.state == RESULT:
            if now - self.state_entered_at >= self.config.post_capture_display_seconds:
                self.state = LIVE
                self.state_entered_at = now

    def _capture_and_flash(self):
        frame = self.camera.read_frame_rgb()
        if frame is not None:
            self.captured_frame = frame
        self.state = FLASH
        self.state_entered_at = time.time()
        self._start_upload()

    def _start_upload(self):
        """Kicks off the upload in the background so it overlaps with the photo review, not after it."""
        if self.captured_frame is None:
            self.upload_queue.put([(False, "Capture failed - no frame from camera")])
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        photo_path = self.config.photos_dir / f"booth_{timestamp}.jpg"
        self.camera.save_frame(self.captured_frame, photo_path)

        def worker():
            results = uploader.post_photo(photo_path, self.config)
            self.upload_queue.put(results)

        threading.Thread(target=worker, daemon=True).start()

    def _advance_after_review(self):
        """Called once the photo review timer expires: skips straight to the result if the upload already
        finished in the background, otherwise shows the uploading spinner until it does."""
        try:
            results = self.upload_queue.get_nowait()
        except queue.Empty:
            self.state = UPLOADING
            self.state_entered_at = time.time()
        else:
            self.result_lines = [msg for _, msg in results]
            self.state = RESULT
            self.state_entered_at = time.time()

    def _draw(self):
        self.screen.fill(BLACK)

        frame = self.captured_frame if self.state in (FLASH, REVIEW, UPLOADING, RESULT) else self.camera.read_frame_rgb()
        if frame is not None:
            surface = frame_to_surface(frame)
            scaled, offset = scale_to_fit(surface, self.screen_size)
            self.screen.blit(scaled, offset)

        if self.state == LIVE:
            self._draw_wrapped_centered_text(self.config.prompt_message, self.font_med, WHITE, y_ratio=0.88)

        elif self.state == COUNTDOWN:
            remaining = self.config.countdown_seconds - (time.time() - self.countdown_start)
            number = max(1, int(remaining) + 1)
            self._draw_centered_text(str(number), self.font_big, WHITE, y_ratio=0.5, shadow=True)

        elif self.state == FLASH:
            self.screen.fill(WHITE)

        elif self.state == REVIEW:
            self._draw_wrapped_centered_text(self.config.review_message_top, self.font_small, WHITE, y_ratio=0.08, shadow=True)
            self._draw_wrapped_centered_text(
                self.config.review_message_bottom, self.font_small, WHITE, y_ratio=0.92, shadow=True
            )

        elif self.state == UPLOADING:
            self._draw_centered_text("Sending your photo...", self.font_med, WHITE, y_ratio=0.9, shadow=True)

        elif self.state == RESULT:
            any_success = any("sent" in line.lower() for line in self.result_lines)
            color = GREEN if any_success else RED
            headline = "Sent!" if any_success else "Something went wrong"
            self._draw_centered_text(headline, self.font_med, color, y_ratio=0.85, shadow=True)
            for i, line in enumerate(self.result_lines):
                self._draw_centered_text(line, self.font_small, WHITE, y_ratio=0.93 + i * 0.03, shadow=True)

        pygame.display.flip()

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
    setup = SetupWindow(raw_config)
    result = setup.run()
    if result is None:
        print("Setup cancelled - exiting.")
        return

    save_config_dict(result)
    config = Config(result)

    try:
        app = BoothApp(config)
    except CameraError as exc:
        print(f"Fatal: {exc}")
        _show_fatal_error(str(exc))
        return
    app.run()


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
