"""Small pygame drawing helpers shared by the booth (app.py) and the start page renderer
(start_screen.py) - which the setup screen also uses for its Start Page preview, drawing onto an
offscreen surface, so everything here takes the surface to draw on rather than assuming the screen."""
import pygame

BLACK = (0, 0, 0)


def frame_to_surface(frame_rgb):
    height, width, _ = frame_rgb.shape
    return pygame.image.frombuffer(frame_rgb.tobytes(), (width, height), "RGB")


def scale_to_fit(surface, target_size):
    target_w, target_h = target_size
    src_w, src_h = surface.get_size()
    scale = min(target_w / src_w, target_h / src_h)
    new_size = (max(1, int(src_w * scale)), max(1, int(src_h * scale)))
    # Camera frames usually arrive already sized to fit (fit_frame) - skip a same-size smoothscale.
    scaled = surface if new_size == (src_w, src_h) else pygame.transform.smoothscale(surface, new_size)
    offset = ((target_w - new_size[0]) // 2, (target_h - new_size[1]) // 2)
    return scaled, offset


def draw_centered_text(surface, text, font, color, y_ratio, shadow=False, shadow_offset=3):
    width, height = surface.get_size()
    if shadow:
        shadow_surf = font.render(text, True, BLACK)
        shadow_rect = shadow_surf.get_rect(center=(width / 2 + shadow_offset, height * y_ratio + shadow_offset))
        surface.blit(shadow_surf, shadow_rect)
    text_surf = font.render(text, True, color)
    text_rect = text_surf.get_rect(center=(width / 2, height * y_ratio))
    surface.blit(text_surf, text_rect)


def draw_wrapped_centered_text(
    surface, text, font, color, y_ratio, shadow=False, max_width_ratio=0.85, shadow_offset=3
):
    width, height = surface.get_size()
    max_width = width * max_width_ratio
    words = text.split()
    lines = [words[0]] if words else [""]
    for word in words[1:]:
        candidate = f"{lines[-1]} {word}"
        if font.size(candidate)[0] <= max_width:
            lines[-1] = candidate
        else:
            lines.append(word)

    line_height = font.get_linesize()
    top = height * y_ratio - (line_height * len(lines)) / 2
    for i, line in enumerate(lines):
        center_y = top + line_height * i + line_height / 2
        if shadow:
            shadow_surf = font.render(line, True, BLACK)
            shadow_rect = shadow_surf.get_rect(center=(width / 2 + shadow_offset, center_y + shadow_offset))
            surface.blit(shadow_surf, shadow_rect)
        text_surf = font.render(line, True, color)
        text_rect = text_surf.get_rect(center=(width / 2, center_y))
        surface.blit(text_surf, text_rect)
