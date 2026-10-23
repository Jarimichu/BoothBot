"""The start page: logo, message and - when turned on - previews of photos taken earlier today
(which photos is photo_gallery.py's call). BoothApp draws it in the booth, and the setup screen's
Start Page tab draws the very same thing onto an offscreen surface as its preview."""
import random
import threading
import time
import zlib
from collections import OrderedDict, deque
from functools import lru_cache
from math import ceil, pi, sin
from pathlib import Path
from typing import NamedTuple

import pygame
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from . import photo_gallery
from .drawing import draw_wrapped_centered_text, scale_to_fit

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
MESSAGE_FONT_SIZE = 64  # BoothApp's font_med - the start message has always used it

# ---------- Settings ----------

LAYOUTS = [
    ("filmstrip", "Filmstrip along bottom"),
    ("columns", "Columns either side"),
    ("scatter", "Polaroid scatter"),
    ("background", "Background slideshow"),
]
MOTIONS = [("static", "Static"), ("rotate", "Rotate"), ("scroll", "Scroll"), ("drift", "Gentle drift")]
# Only the motions that make sense for each layout are offered - a scrolling full-screen background
# or a conveyor belt of tilted prints would just look odd.
MOTIONS_BY_LAYOUT = {
    "filmstrip": ["static", "rotate", "scroll"],
    "columns": ["static", "rotate", "scroll"],
    "scatter": ["static", "rotate", "drift"],
    "background": ["static", "rotate"],
}
DEFAULT_MOTION = {"filmstrip": "rotate", "columns": "scroll", "scatter": "drift", "background": "rotate"}
COUNT_CHOICES = {
    "filmstrip": [3, 4, 5, 6, 7, 8],
    "columns": [2, 4, 6, 8],  # split evenly between the two sides
    "scatter": [3, 4, 5, 6, 7, 8],
    "background": [1],
}
DEFAULT_COUNT = {"filmstrip": 5, "columns": 6, "scatter": 6, "background": 1}
# Filmstrip and columns only - scatter is always polaroid prints, and background has no frame.
# The "halo" is light rather than a dark drop shadow, which wouldn't show on the black background.
FRAMES = [("white", "White border"), ("halo", "Thin border + halo"), ("rounded", "Rounded, no border")]
SPEEDS = [("slow", "Slow"), ("medium", "Medium"), ("fast", "Fast")]

ROTATE_INTERVAL_S = {"slow": 8.0, "medium": 5.0, "fast": 3.0}
BACKGROUND_INTERVAL_S = {"slow": 14.0, "medium": 9.0, "fast": 6.0}
SCROLL_CROSSING_S = {"slow": 45.0, "medium": 30.0, "fast": 18.0}  # one tile's trip across the screen
DRIFT_PERIOD_S = {"slow": 7.0, "medium": 5.0, "fast": 3.0}


class PreviewSettings(NamedTuple):
    enabled: bool
    layout: str
    motion: str
    count: int
    frame: str
    speed: str
    delay_s: int
    uploaded_only: bool
    photo_aspect: float  # width / height of the photos' slots - the camera's aspect ratio


def _as_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def preview_settings(values) -> PreviewSettings:
    """The preview settings from a config dict (or vars(Config)), with anything invalid - a
    hand-edited config.json, say - replaced by a default rather than stopping the booth."""
    layout = values.get("start_previews_layout")
    if layout not in MOTIONS_BY_LAYOUT:
        layout = "scatter"
    motion = values.get("start_previews_motion")
    if motion not in MOTIONS_BY_LAYOUT[layout]:
        motion = DEFAULT_MOTION[layout]
    choices = COUNT_CHOICES[layout]
    count = _as_int(values.get("start_previews_count"), DEFAULT_COUNT[layout])
    count = min(choices, key=lambda choice: abs(choice - count))
    frame = values.get("start_previews_frame")
    if frame not in dict(FRAMES):
        frame = "white"
    speed = values.get("start_previews_speed")
    if speed not in dict(SPEEDS):
        speed = "medium"
    width = _as_int(values.get("camera_width"), 0)
    height = _as_int(values.get("camera_height"), 0)
    aspect = width / height if width > 0 and height > 0 else 16 / 9
    return PreviewSettings(
        enabled=bool(values.get("start_previews_enabled", False)),
        layout=layout,
        motion=motion,
        count=count,
        frame=frame,
        speed=speed,
        delay_s=max(0, _as_int(values.get("start_previews_delay_seconds"), 60)),
        uploaded_only=bool(values.get("start_previews_uploaded_only", True)),
        photo_aspect=min(max(aspect, 1.0), 2.0),
    )


# ---------- Tile rendering (PreviewFeed's thread) ----------

RESCAN_INTERVAL_S = 3
SAMPLE_LIMIT = 24
READY_LIMIT = 32  # rendered tiles waiting to be picked up - only grows if nobody asks for them again
BACKGROUND_BRIGHTNESS = 0.45  # dark enough for the white message to stay readable on top
GLOW_COLOR = (255, 214, 120)
PAPER_COLOR = (248, 246, 240)
CAPTION_COLOR = (70, 70, 80)
# Windows' handwriting-style fonts, in order of preference; Pillow finds bare names in the Fonts folder.
CAPTION_FONTS = ("segoepr.ttf", "inkfree.ttf", "comic.ttf")


class TileSpec(NamedTuple):
    """Everything that decides what one rendered tile looks like - also its cache key."""
    path: str  # "" for a glow
    kind: str  # "white" | "halo" | "rounded" | "polaroid" | "background" | "glow"
    size: tuple  # the photo's size; for a glow, the outer size of the tile it surrounds
    angle: float = 0.0
    caption: str = ""


def _tile_pad(kind, photo_size):
    """(sides, top, bottom) frame thickness around the photo."""
    photo_w, photo_h = photo_size
    if kind == "white":
        border = max(2, round(photo_h * 0.045))
        return border, border, border
    if kind == "halo":
        border = max(1, round(photo_h * 0.008))
        return border, border, border
    if kind == "polaroid":
        border = max(2, round(photo_w * 0.05))
        return border, border, max(4, round(photo_h * 0.24))
    return 0, 0, 0


def tile_outer_size(kind, photo_size):
    sides, top, bottom = _tile_pad(kind, photo_size)
    return photo_size[0] + 2 * sides, photo_size[1] + top + bottom


@lru_cache(maxsize=8)
def _caption_font(size):
    for name in CAPTION_FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _rounded_mask(size, radius):
    # Drawn 4x and scaled down - ImageDraw doesn't antialias, and jagged corners show at 4K.
    factor = 4
    big = Image.new("L", (size[0] * factor, size[1] * factor), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, big.width - 1, big.height - 1), radius=radius * factor, fill=255)
    return big.resize(size, Image.Resampling.LANCZOS)


def _with_shadow(tile, blur, offset, color, strength):
    """tile on a canvas with a soft blurred copy of its outline behind it. The margins are equal on
    every side, so the tile stays centred - it's positioned by its centre when drawn."""
    margin = 2 * blur + offset
    size = (tile.width + 2 * margin, tile.height + 2 * margin)
    alpha = Image.new("L", size, 0)
    left = top = margin + offset
    ImageDraw.Draw(alpha).rectangle((left, top, left + tile.width - 1, top + tile.height - 1), fill=strength)
    canvas = Image.new("RGBA", size, color + (0,))
    canvas.putalpha(alpha.filter(ImageFilter.GaussianBlur(blur)))
    canvas.alpha_composite(tile, (margin, margin))
    return canvas


def _render_glow(spec):
    outer_w, outer_h = spec.size
    spread = max(3, round(min(outer_w, outer_h) * 0.09))
    margin = spread * 3
    size = (outer_w + 2 * margin, outer_h + 2 * margin)
    alpha = Image.new("L", size, 0)
    ImageDraw.Draw(alpha).rounded_rectangle(
        (margin - spread, margin - spread, margin + outer_w + spread - 1, margin + outer_h + spread - 1),
        radius=spread * 2, fill=255,
    )
    glow = Image.new("RGBA", size, GLOW_COLOR + (0,))
    glow.putalpha(alpha.filter(ImageFilter.GaussianBlur(spread)))
    if spec.angle:
        glow = glow.rotate(spec.angle, resample=Image.Resampling.BICUBIC, expand=True)
    return glow.tobytes(), glow.size, "RGBA"


def _render_background(photo, size):
    # Blurred at a quarter size and scaled back up: far cheaper than blurring a 4K image, and the
    # blur hides the upscale anyway.
    small = (max(1, size[0] // 4), max(1, size[1] // 4))
    image = ImageOps.fit(photo, small, Image.Resampling.BILINEAR)
    image = image.filter(ImageFilter.GaussianBlur(max(2, small[0] // 160)))
    image = image.point(lambda value: int(value * BACKGROUND_BRIGHTNESS))
    image = image.resize(size, Image.Resampling.BILINEAR)
    return image.tobytes(), image.size, "RGB"


def _render_tile(spec):
    """(raw bytes, size, "RGB"/"RGBA") for one tile - photo decoded, cropped to fill its slot, framed."""
    if spec.kind == "glow":
        return _render_glow(spec)

    draft_size = (spec.size[0] // 4, spec.size[1] // 4) if spec.kind == "background" else spec.size
    with Image.open(spec.path) as source:
        # JPEGs decode straight at 1/2, 1/4 or 1/8 size (never below draft_size) - several times
        # faster than decoding a 4K photo in full just to shrink it to a thumbnail.
        source.draft("RGB", draft_size)
        photo = source.convert("RGB")
    if spec.kind == "background":
        return _render_background(photo, spec.size)

    photo = ImageOps.fit(photo, spec.size, Image.Resampling.LANCZOS)
    photo_w, photo_h = spec.size
    if spec.kind == "rounded":
        tile = photo.convert("RGBA")
        tile.putalpha(_rounded_mask(spec.size, max(2, round(photo_h * 0.07))))
        return tile.tobytes(), tile.size, "RGBA"

    sides, top, bottom = _tile_pad(spec.kind, spec.size)
    paper = PAPER_COLOR if spec.kind == "polaroid" else (250, 250, 250) if spec.kind == "white" else (235, 235, 235)
    tile = Image.new("RGBA", tile_outer_size(spec.kind, spec.size), paper + (255,))
    tile.paste(photo, (sides, top))
    if spec.kind == "polaroid":
        draw = ImageDraw.Draw(tile)
        draw.rectangle((0, 0, tile.width - 1, tile.height - 1), outline=(215, 212, 205))
        if spec.caption:
            font = _caption_font(max(6, round(bottom * 0.5)))
            draw.text((tile.width / 2, top + photo_h + bottom / 2), spec.caption, font=font, fill=CAPTION_COLOR, anchor="mm")
        # A dark shadow - it shows where prints overlap, which is what gives the pile its depth.
        tile = _with_shadow(tile, max(2, round(photo_h * 0.035)), max(1, round(photo_h * 0.02)), (0, 0, 0), 150)
        tile = tile.rotate(spec.angle, resample=Image.Resampling.BICUBIC, expand=True)
    elif spec.kind == "halo":
        tile = _with_shadow(tile, max(2, round(photo_h * 0.04)), 0, (255, 255, 255), 70)
    return tile.tobytes(), tile.size, "RGBA"


PENDING = object()  # PreviewFeed.fetch / TileCache.get: still rendering, ask again next frame


class PreviewFeed:
    """Finds the photos to preview and renders their tiles on one background thread, so listing the
    photos folder, reading captures.csv and decoding JPEGs never stall drawing. The scan result is
    handed over by a single attribute assignment; rendered tiles under _lock."""

    def __init__(self, photos_dir, delay_s, uploaded_only, sample_fallback=False):
        self.photos_dir = photos_dir
        self._rules = (delay_s, uploaded_only)
        # Setup's preview only: with nothing from today eligible, show the newest photos of any day
        # instead, so the layout can still be judged with real photos.
        self._sample_fallback = sample_fallback
        # (photos, using_samples) - photos is [(path, captured_at)], newest first. None until the
        # first scan finishes; always replaced as a whole, never mutated.
        self.result = None
        self._active = True
        self._rescan_requested = True
        self._lock = threading.Lock()
        self._queued = OrderedDict()  # TileSpec -> None, oldest request first
        self._ready = OrderedDict()  # TileSpec -> rendered tuple, or None if it couldn't be rendered
        self._wake = threading.Event()
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def set_rules(self, delay_s, uploaded_only):
        if (delay_s, uploaded_only) != self._rules:
            self._rules = (delay_s, uploaded_only)
            self.rescan()

    def set_active(self, active):
        """Scanning pauses while inactive (the booth outside its start page, or setup on another tab)."""
        if active and not self._active:
            self._rescan_requested = True
            self._wake.set()
        self._active = active

    def rescan(self):
        self._rescan_requested = True
        self._wake.set()

    def stop(self):
        self._stopped.set()
        self._wake.set()

    def fetch(self, spec):
        """The rendered tile - (bytes, size, mode), or None if it couldn't be rendered (e.g. the
        photo was deleted) - or PENDING, having queued it, while it's still being rendered."""
        with self._lock:
            if spec in self._ready:
                return self._ready.pop(spec)
            if spec not in self._queued:
                self._queued[spec] = None
                self._wake.set()
        return PENDING

    def _run(self):
        next_scan = 0.0
        while not self._stopped.is_set():
            self._wake.clear()
            if self._active and (self._rescan_requested or time.monotonic() >= next_scan):
                self._rescan_requested = False
                self._scan()
                next_scan = time.monotonic() + RESCAN_INTERVAL_S
            while not self._stopped.is_set() and self._render_next():
                pass
            self._wake.wait(max(0.05, next_scan - time.monotonic()) if self._active else None)

    def _scan(self):
        delay_s, uploaded_only = self._rules
        try:
            photos = photo_gallery.eligible_photos(self.photos_dir, delay_s=delay_s, uploaded_only=uploaded_only)
            using_samples = False
            if not photos and self._sample_fallback:
                photos = photo_gallery.sample_photos(self.photos_dir, SAMPLE_LIMIT)
                using_samples = bool(photos)
        except Exception as exc:
            # Runs unattended for the whole session - a surprise here must not kill the thread.
            print(f"Could not scan photos for the start page: {exc}")
            return
        self.result = (photos, using_samples)

    def _render_next(self):
        with self._lock:
            if not self._queued:
                return False
            spec = next(iter(self._queued))
        try:
            rendered = _render_tile(spec)
        except Exception as exc:
            print(f"Could not prepare start page photo '{spec.path}': {exc}")
            rendered = None
        with self._lock:
            self._queued.pop(spec, None)
            self._ready[spec] = rendered
            while len(self._ready) > READY_LIMIT:
                self._ready.popitem(last=False)
        return True


class TileCache:
    """pygame surfaces made from PreviewFeed's rendered tiles, by TileSpec - main thread only. The
    setup preview keeps one across its StartScreen rebuilds (one per settings change), so tiles that
    didn't change aren't rendered again."""

    def __init__(self):
        self.limit = 32
        self._surfaces = OrderedDict()

    def get(self, feed, spec):
        """A surface, None if the tile couldn't be rendered, or PENDING."""
        if spec in self._surfaces:
            self._surfaces.move_to_end(spec)
            return self._surfaces[spec]
        rendered = feed.fetch(spec)
        if rendered is PENDING:
            return PENDING
        surface = None if rendered is None else _to_surface(*rendered)
        self._surfaces[spec] = surface
        while len(self._surfaces) > self.limit:
            self._surfaces.popitem(last=False)
        return surface


def _to_surface(data, size, mode):
    surface = pygame.image.frombuffer(data, size, mode)
    # The setup preview has no display to convert for - and doesn't need the faster blits anyway.
    if pygame.display.get_surface() is None:
        return surface
    return surface.convert_alpha() if mode == "RGBA" else surface.convert()


def load_logo(path):
    """The start page logo, unscaled, or None (saying why) if none is set or it can't be loaded."""
    if not path:
        return None
    logo_path = Path(path)
    if not logo_path.exists():
        print(f"Start logo not found: {logo_path}")
        return None
    try:
        image = pygame.image.load(str(logo_path))
    except pygame.error as exc:
        print(f"Could not load start logo '{logo_path}': {exc}")
        return None
    return image.convert_alpha() if pygame.display.get_surface() is not None else image


# ---------- Layout and motion ----------

class _TextLayout(NamedTuple):
    logo_box: tuple  # (width, height), as fractions of the screen
    logo_y: float
    message_y: float  # below a logo
    message_y_no_logo: float
    message_width: float


PLAIN_TEXT = _TextLayout((0.5, 0.45), 0.42, 0.78, 0.5, 0.85)  # the start page as it's always been
PREVIEW_TEXT = {
    "filmstrip": _TextLayout((0.5, 0.36), 0.26, 0.56, 0.36, 0.85),
    "columns": _TextLayout((0.46, 0.45), 0.42, 0.78, 0.5, 0.5),
    "scatter": _TextLayout((0.46, 0.45), 0.42, 0.78, 0.5, 0.5),
    "background": PLAIN_TEXT,
}
FILMSTRIP_Y = 0.81
COLUMN_X = 0.13  # and 1 - this; the columns are ~0.2 of the screen wide
SCATTER_X = 0.14

CROSSFADE_S = 0.8
BACKGROUND_CROSSFADE_S = 1.5
TILE_FADE_IN_S = 0.3
POP_IN_S = 0.5
POP_START_SCALE = 0.6
GLOW_S = 4.5  # from the start of the pop-in, the last second fading out
GLOW_PULSE_S = 1.1
LAYOUT_DIP_S = 0.6  # empty <-> with photos: a quick dip to black, so the logo never visibly jumps
FIRST_SCAN_GRACE_S = 1.5  # a first scan landing this soon just switches, no dip
NEWEST_WEIGHT = 0.65  # rotate/scroll: chance the next photo comes from the newest 2 x count
DRIFT_AMPLITUDE = 0.01  # of the screen height


def _tilt(name):
    """A print's angle, from its filename so it's the same every time it's shown: ±3-8 degrees."""
    digest = zlib.crc32(name.encode("utf-8"))
    angle = 3 + (digest % 501) / 100
    return angle if digest & 0x10000 else -angle


def _caption(captured_at):
    return captured_at.strftime("%I:%M %p").lstrip("0")


def _ease_out_back(t):
    overshoot = 1.70158
    return 1 + (overshoot + 1) * (t - 1) ** 3 + overshoot * (t - 1) ** 2


def _blit_centered(surface, tile, center, alpha=255):
    if alpha <= 0:
        return
    rect = tile.get_rect(center=(round(center[0]), round(center[1])))
    if alpha >= 255:
        surface.blit(tile, rect)
        return
    tile.set_alpha(alpha)
    surface.blit(tile, rect)
    tile.set_alpha(None)  # it's a cached surface - don't leave it faded


class _Slot:
    """A photo on screen, plus what's needed to animate it arriving there."""

    def __init__(self, photo, previous=None, arrival=False, pops=True):
        self.photo = photo  # (path, captured_at)
        self.previous = previous  # the photo being crossfaded away from, if any
        self.arrival = arrival  # newly eligible: gets the glow, and the pop-in if pops
        self.pops = pops
        self.ready_at = None  # when its tile was first drawable - animations run from here
        self.glow_from = None

    @property
    def name(self):
        return self.photo[0].name


class _Lane:
    """A line of tiles scrolling past - the filmstrip, or one column. Positions run along the line;
    tiles enter at one end of the screen and leave at the other."""

    def __init__(self, fixed, extent, step, direction, horizontal):
        self.fixed = fixed  # the other coordinate, shared by every tile in the lane
        self.extent = extent  # screen length along the lane
        self.step = step  # tile + gap
        self.direction = direction  # -1 moves toward 0 (entering at extent), +1 the other way
        self.horizontal = horizontal
        self.tiles = deque()  # [position, slot], the one nearest the exit first

    def center(self, position):
        return (position, self.fixed) if self.horizontal else (self.fixed, position)

    def on_screen(self, position):
        return -self.step / 2 < position < self.extent + self.step / 2

    def needs_tile(self):
        if not self.tiles:
            return True
        last = self.tiles[-1][0]
        return last < self.extent + self.step / 2 if self.direction < 0 else last > -self.step / 2

    def next_position(self):
        if self.tiles:
            return self.tiles[-1][0] - self.direction * self.step
        return self.step / 2 if self.direction < 0 else self.extent - self.step / 2

    def gone(self, position):
        return position < -self.step / 2 if self.direction < 0 else position > self.extent + self.step / 2


class StartScreen:
    """Draws the start page onto a surface already cleared to black. scale shrinks the fonts and
    fixed pixel sizes for the setup preview, which draws a scaled-down copy of the booth's screen.
    feed None means no previews - exactly the start page as it was before previews existed."""

    def __init__(self, size, *, settings, message, logo, feed=None, tiles=None, scale=1.0):
        pygame.font.init()
        self.size = size
        self.settings = settings
        self.message = message  # may be changed directly - the setup preview does as you type
        self.feed = feed if settings.enabled else None
        self.tiles = tiles if tiles is not None else TileCache()
        self.scale = scale
        self.font = pygame.font.SysFont("Arial", max(6, round(MESSAGE_FONT_SIZE * scale)), bold=True)

        layout = settings.layout
        self._kind = {"scatter": "polaroid", "background": "background"}.get(layout, settings.frame)
        self._ordered = layout in ("filmstrip", "columns")  # static: newest first, in order
        self._preview_text = PREVIEW_TEXT[layout]
        self._logos = {}
        for text_layout in (PLAIN_TEXT, self._preview_text):
            if text_layout not in self._logos:
                box = (round(size[0] * text_layout.logo_box[0]), round(size[1] * text_layout.logo_box[1]))
                self._logos[text_layout] = scale_to_fit(logo, box)[0] if logo is not None else None
        self._build_geometry()
        self.tiles.limit = 4 if layout == "background" else 3 * settings.count + 8

        now = time.monotonic()
        self._created_at = now
        self._feed_result = None
        self._photos = []
        self._known = None  # names seen so far - anything new after the first scan is an arrival
        self._broken = set()  # names whose tile couldn't be rendered
        self._needs_apply = False
        self._slots = []
        self._lanes = None
        self._scroll_queue = deque()
        self._arrivals = deque()
        self._recent = deque(maxlen=max(3, settings.count))
        self._rotate_index = 0
        self._last_rotate = now
        self._target_populated = False
        self._shown_populated = False
        self._dip_started = None
        self._overlay = None
        self._last_draw_at = now
        self._frames_drawn = 0

    @property
    def using_samples(self):
        return bool(self._feed_result and self._feed_result[1])

    @property
    def photo_count(self):
        return len(self._photos)

    # ----- geometry -----

    def _build_geometry(self):
        width, height = self.size
        settings = self.settings
        count = settings.count
        aspect = settings.photo_aspect
        # How much the frame adds around a photo, per unit of photo width/height.
        sample = tile_outer_size(self._kind, (round(aspect * 1000), 1000))
        outer_w_ratio, outer_h_ratio = sample[0] / (aspect * 1000), sample[1] / 1000
        self._gap = 0.0
        if settings.layout == "filmstrip":
            self._gap = width * 0.02
            photo_w = min(height * 0.21 * aspect, (width * 0.94 - (count - 1) * self._gap) / count / outer_w_ratio)
        elif settings.layout == "columns":
            per_side = count // 2
            self._gap = height * 0.03
            photo_h = (height * 0.92 - (per_side - 1) * self._gap) / per_side / outer_h_ratio
            photo_w = min(width * 0.2 / outer_w_ratio, photo_h * aspect)
        elif settings.layout == "scatter":
            # Prints may overlap a little - it's a pile, not a grid.
            per_side = ceil(count / 2)
            photo_w = min(width * 0.17, height * 0.94 / per_side * 1.08 / outer_h_ratio * aspect)
        else:
            photo_w = width
        if settings.layout == "background":
            self._photo_size = self.size
        else:
            self._photo_size = (max(8, round(photo_w)), max(8, round(photo_w / aspect)))
        self._outer = tile_outer_size(self._kind, self._photo_size)
        self._positions_cache = {}

    def _positions(self, visible):
        """Centres of the first `visible` slots."""
        if visible not in self._positions_cache:
            self._positions_cache[visible] = self._compute_positions(visible)
        return self._positions_cache[visible]

    def _compute_positions(self, visible):
        width, height = self.size
        outer_w, outer_h = self._outer
        layout = self.settings.layout
        if layout == "background":
            return [(width / 2, height / 2)] * visible
        if layout == "filmstrip":
            step = outer_w + self._gap
            first = (width - (visible * outer_w + (visible - 1) * self._gap)) / 2 + outer_w / 2
            return [(first + i * step, height * FILMSTRIP_Y) for i in range(visible)]

        # Columns and scatter alternate left/right, each side's stack centred on its own.
        sides = ([], [])
        for i in range(visible):
            sides[i % 2].append(i)
        positions = [None] * visible
        for side, indices in enumerate(sides):
            stacked = len(indices)
            for j, i in enumerate(indices):
                if layout == "columns":
                    x = width * (COLUMN_X if side == 0 else 1 - COLUMN_X)
                    first = (height - (stacked * outer_h + (stacked - 1) * self._gap)) / 2 + outer_h / 2
                    positions[i] = (x, first + j * (outer_h + self._gap))
                else:
                    # Fixed per position (not per photo), so prints don't wander between rescans.
                    jitter = random.Random(f"{side}-{j}-{stacked}")
                    x = width * (SCATTER_X if side == 0 else 1 - SCATTER_X) + jitter.uniform(-1, 1) * width * 0.02
                    y = height * (j + 0.5) / stacked + jitter.uniform(-1, 1) * height * 0.025
                    y = min(max(y, outer_h * 0.5), height - outer_h * 0.5)
                    positions[i] = (x, y)
        return positions

    def _make_lanes(self):
        width, height = self.size
        outer_w, outer_h = self._outer
        if self.settings.layout == "filmstrip":
            return [_Lane(height * FILMSTRIP_Y, width, outer_w + self._gap, -1, True)]
        step = outer_h + self._gap
        return [
            _Lane(width * COLUMN_X, height, step, -1, False),  # left column rises
            _Lane(width * (1 - COLUMN_X), height, step, +1, False),  # right column falls
        ]

    def _lane_capacity(self):
        """How many tiles the lanes can show at once - scrolling needs more photos than that, or the
        same photo would be on screen twice."""
        width, height = self.size
        outer_w, outer_h = self._outer
        if self.settings.layout == "filmstrip":
            return ceil(width / (outer_w + self._gap)) + 1
        return 2 * (ceil(height / (outer_h + self._gap)) + 1)

    def _mode(self):
        motion = self.settings.motion
        if motion == "scroll" and len(self._photos) <= self._lane_capacity():
            return "static"
        if motion == "rotate" and len(self._photos) <= self.settings.count:
            return "static"
        return motion

    # ----- choosing photos -----

    def _spec(self, photo):
        path, captured_at = photo
        if self._kind == "background":
            return TileSpec(str(path), "background", self.size)
        if self._kind == "polaroid":
            return TileSpec(str(path), "polaroid", self._photo_size, _tilt(path.name), _caption(captured_at))
        return TileSpec(str(path), self._kind, self._photo_size)

    def _tile(self, photo):
        return self.tiles.get(self.feed, self._spec(photo))

    def _pick(self, exclude):
        """The next photo to rotate/scroll in: mostly recent ones, the rest of the day now and then."""
        candidates = [photo for photo in self._photos if photo[0].name not in exclude]
        if not candidates:
            return None
        fresh = [photo for photo in candidates if photo[0].name not in self._recent] or candidates
        newest_count = max(4, 2 * self.settings.count)
        newest, rest = fresh[:newest_count], fresh[newest_count:]
        photo = random.choice(rest if rest and random.random() >= NEWEST_WEIGHT else newest)
        self._recent.append(photo[0].name)
        return photo

    def _poll_feed(self, now):
        if self.feed is None:
            return
        result = self.feed.result
        if result is not None and (result is not self._feed_result or self._needs_apply):
            first = self._feed_result is None
            self._feed_result = result
            self._needs_apply = False
            self._apply(result[0], now, first)

    def _apply(self, photos, now, first):
        photos = [photo for photo in photos if photo[0].name not in self._broken]
        names = {photo[0].name for photo in photos}
        if self._known is None:
            self._known = set(names)
            arrivals = []
        else:
            arrivals = [photo for photo in photos if photo[0].name not in self._known]
            self._known |= names
        if self.settings.layout == "background":
            arrivals_glow = []  # a full-screen photo just crossfades in
        else:
            arrivals_glow = arrivals
        self._photos = photos

        populated = bool(photos)
        if populated != self._target_populated:
            self._target_populated = populated
            if first and now - self._created_at < FIRST_SCAN_GRACE_S:
                self._shown_populated = populated
            elif self._dip_started is None:
                self._dip_started = now

        if self._mode() == "scroll":
            self._slots = []
            if self._lanes is None:
                self._lanes = self._make_lanes()
                self._scroll_queue = deque(photos[:self._lane_capacity()])
                self._arrivals.clear()
            else:
                self._arrivals.extend(arrivals_glow)
                self._replace_ineligible_in_lanes(names)
            return
        self._lanes = None
        self._arrivals.clear()
        self._reconcile_slots(names, {photo[0].name for photo in arrivals_glow}, now)

    def _reconcile_slots(self, names, arrival_names, now):
        old = self._slots
        count = min(self.settings.count, len(self._photos))

        def make(photo, i):
            previous = old[i].photo if i < len(old) else None
            return _Slot(photo, previous=previous, arrival=photo[0].name in arrival_names)

        if self._mode() == "rotate":
            if not old:
                self._slots = [_Slot(photo) for photo in self._photos[:count]]
                return
            slots = [old[i] if i < len(old) and old[i].name in names else None for i in range(count)]
            # Newly eligible photos go up straight away, into the slots next in line to rotate.
            for photo in reversed([photo for photo in self._photos if photo[0].name in arrival_names][:count]):
                i = self._rotate_index % count
                self._rotate_index += 1
                slots[i] = make(photo, i)
                self._last_rotate = now
            for i in range(count):
                if slots[i] is None:
                    pick = self._pick({slot.name for slot in slots if slot is not None})
                    if pick is not None:
                        slots[i] = make(pick, i)
            self._slots = [slot for slot in slots if slot is not None]
            return

        desired = self._photos[:count]
        if self._ordered:
            # Static filmstrip/columns: newest first, in order - a new photo shifts the rest along.
            self._slots = [
                old[i] if i < len(old) and old[i].name == photo[0].name else make(photo, i)
                for i, photo in enumerate(desired)
            ]
            return
        # Scatter/background: photos stay where they are; a new one takes the place of the one
        # that dropped out of the newest `count`.
        desired_names = {photo[0].name for photo in desired}
        slots = [slot if slot.name in desired_names else None for slot in old[:count]]
        shown = {slot.name for slot in slots if slot is not None}
        waiting = deque(photo for photo in desired if photo[0].name not in shown)
        for i in range(len(slots)):
            if slots[i] is None and waiting:
                slots[i] = make(waiting.popleft(), i)
        while len(slots) < count and waiting:
            slots.append(make(waiting.popleft(), len(slots)))
        self._slots = [slot for slot in slots if slot is not None]

    def _replace_ineligible_in_lanes(self, names):
        # A photo hidden from the Logs tab (or past the 4 AM rollover) goes at once, not when it
        # scrolls off.
        shown = {slot.name for lane in self._lanes for _, slot in lane.tiles}
        for lane in self._lanes:
            for tile in lane.tiles:
                if tile[1].name not in names:
                    pick = self._pick(shown)
                    if pick is not None:
                        shown.add(pick[0].name)
                        tile[1] = _Slot(pick, previous=tile[1].photo)

    def _next_scroll_photo(self, shown):
        if self._arrivals:
            return self._arrivals.popleft(), True
        while self._scroll_queue:
            photo = self._scroll_queue.popleft()
            if photo[0].name not in shown:
                return photo, False
        return self._pick(shown), False

    def _advance_lanes(self, elapsed):
        speed_s = SCROLL_CROSSING_S[self.settings.speed]
        for lane in self._lanes:
            distance = (lane.extent + lane.step) / speed_s * elapsed
            for tile in lane.tiles:
                tile[0] += lane.direction * distance
            while lane.tiles and lane.gone(lane.tiles[0][0]):
                lane.tiles.popleft()
        shown = {slot.name for lane in self._lanes for _, slot in lane.tiles}
        for lane in self._lanes:
            while lane.needs_tile():
                photo, arrival = self._next_scroll_photo(shown)
                if photo is None:
                    break
                shown.add(photo[0].name)
                lane.tiles.append([lane.next_position(), _Slot(photo, arrival=arrival, pops=False)])

    def _maybe_rotate(self, now):
        interval = (BACKGROUND_INTERVAL_S if self.settings.layout == "background" else ROTATE_INTERVAL_S)[
            self.settings.speed
        ]
        if not self._slots or now - self._last_rotate < interval:
            return
        i = self._rotate_index % len(self._slots)
        self._rotate_index += 1
        self._last_rotate = now
        pick = self._pick({slot.name for slot in self._slots})
        if pick is not None:
            self._slots[i] = _Slot(pick, previous=self._slots[i].photo)

    # ----- drawing -----

    def draw(self, surface, now=None):
        now = time.monotonic() if now is None else now
        elapsed = min(now - self._last_draw_at, 0.1)  # don't leap after time away from the start page
        self._last_draw_at = now
        self._poll_feed(now)

        overlay = 0
        if self._dip_started is not None:
            progress = (now - self._dip_started) / LAYOUT_DIP_S
            if progress >= 0.5:
                self._shown_populated = self._target_populated
            if progress >= 1:
                self._dip_started = None
            else:
                overlay = round(255 * (1 - abs(2 * progress - 1)))

        # Follows _shown_populated, not whether there are photos right now: when the last one goes
        # (hidden, or the 4 AM rollover), the layout holds until the dip has gone dark.
        populated = self._shown_populated
        if populated:
            self._draw_previews(surface, now, elapsed)
        text_layout = self._preview_text if populated else PLAIN_TEXT
        self._draw_text(surface, text_layout, shadow=populated and self.settings.layout == "background")

        if overlay:
            if self._overlay is None:
                self._overlay = pygame.Surface(self.size)
                self._overlay.fill(BLACK)
            _blit_centered(surface, self._overlay, (self.size[0] / 2, self.size[1] / 2), overlay)
        self._frames_drawn += 1

    def _draw_text(self, surface, text_layout, shadow):
        width, height = self.size
        logo = self._logos[text_layout]
        message_y = text_layout.message_y_no_logo
        if logo is not None:
            surface.blit(logo, logo.get_rect(center=(width / 2, height * text_layout.logo_y)))
            message_y = text_layout.message_y
        draw_wrapped_centered_text(
            surface, self.message, self.font, WHITE, y_ratio=message_y, shadow=shadow,
            max_width_ratio=text_layout.message_width, shadow_offset=max(1, round(3 * self.scale)),
        )

    def _draw_previews(self, surface, now, elapsed):
        mode = self._mode()
        if mode == "scroll" and self._lanes is not None:
            self._advance_lanes(elapsed)
            for lane in self._lanes:
                for position, slot in lane.tiles:
                    if slot.arrival and slot.glow_from is None and lane.on_screen(position):
                        slot.glow_from = now
                    self._draw_slot(surface, slot, lane.center(position), now)
            return

        if mode == "rotate":
            self._maybe_rotate(now)
        positions = self._positions(len(self._slots))
        for i, (slot, (x, y)) in enumerate(zip(self._slots, positions)):
            if mode == "drift":
                period = DRIFT_PERIOD_S[self.settings.speed]
                amplitude = self.size[1] * DRIFT_AMPLITUDE
                phase = i * 2.1
                x += amplitude * 0.5 * sin(2 * pi * now / (period * 1.3) + phase * 1.7)
                y += amplitude * sin(2 * pi * now / period + phase)
            self._draw_slot(surface, slot, (x, y), now)

    def _draw_slot(self, surface, slot, center, now):
        tile = self._tile(slot.photo)
        if not isinstance(tile, pygame.Surface):
            if tile is None and slot.name not in self._broken:
                self._broken.add(slot.name)
                self._needs_apply = True  # swap it for another photo on the next frame
            if slot.previous is not None:  # keep showing the old photo until the new one's ready
                old = self._tile(slot.previous)
                if isinstance(old, pygame.Surface):
                    _blit_centered(surface, old, center)
            return

        if slot.ready_at is None:
            slot.ready_at = now
            if slot.arrival and slot.pops:
                slot.glow_from = now
            elif self._frames_drawn == 0 and slot.previous is None:
                # Already rendered when this StartScreen was built (setup rebuilds it on every
                # settings change) - just show it, no fade-in blink.
                slot.ready_at = now - TILE_FADE_IN_S
        age = now - slot.ready_at

        if slot.glow_from is not None:
            glow_age = now - slot.glow_from
            if glow_age < GLOW_S:
                angle = _tilt(slot.name) if self._kind == "polaroid" else 0.0
                glow = self.tiles.get(self.feed, TileSpec("", "glow", self._outer, angle))
                if isinstance(glow, pygame.Surface):
                    pulse = 0.65 + 0.35 * sin(2 * pi * glow_age / GLOW_PULSE_S)
                    fade = min(1.0, (GLOW_S - glow_age) / 1.0)
                    _blit_centered(surface, glow, center, round(255 * pulse * fade))
            else:
                slot.glow_from = None
                slot.arrival = False

        old = self._tile(slot.previous) if slot.previous is not None else None
        same_footprint = self._kind != "polaroid"  # tilted prints differ in shape, so fade both
        if slot.arrival and slot.pops and age < POP_IN_S:
            progress = age / POP_IN_S
            if isinstance(old, pygame.Surface):
                _blit_centered(surface, old, center, round(255 * (1 - progress)))
            scale = POP_START_SCALE + (1 - POP_START_SCALE) * _ease_out_back(progress)
            popped = pygame.transform.smoothscale(
                tile, (max(1, round(tile.get_width() * scale)), max(1, round(tile.get_height() * scale)))
            )
            _blit_centered(surface, popped, center, round(255 * min(1.0, progress / 0.4)))
            return
        if slot.previous is not None:
            duration = BACKGROUND_CROSSFADE_S if self._kind == "background" else CROSSFADE_S
            if age < duration:
                progress = age / duration
                if isinstance(old, pygame.Surface):
                    _blit_centered(surface, old, center, 255 if same_footprint else round(255 * (1 - progress)))
                _blit_centered(surface, tile, center, round(255 * progress))
                return
            slot.previous = None
        if age < TILE_FADE_IN_S:
            _blit_centered(surface, tile, center, round(255 * age / TILE_FADE_IN_S))
            return
        _blit_centered(surface, tile, center)
