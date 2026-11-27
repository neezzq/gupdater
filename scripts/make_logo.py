"""Draw the GUpdater logo: a graphite "liquid glass" tile with a refresh-arrow G.

Run once after changing the design; the results are committed:
    python scripts/make_logo.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "gupdater" / "assets"
S = 2048          # drawing size (twice the final 1024 px, for smooth edges)
K = S / 1024


def px(v: float) -> int:
    return round(v * K)


def vertical_gradient(size, stops):
    """stops: [(position 0..1, (r, g, b, a)), ...]"""
    w, h = size
    column = Image.new("RGBA", (1, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
            if p0 <= t <= p1:
                f = (t - p0) / max(p1 - p0, 1e-9)
                column.putpixel((0, y), tuple(round(a + (b - a) * f) for a, b in zip(c0, c1)))
                break
    return column.resize((w, h))


def radial(size, center, radius, color):
    w, h = size
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    steps = 64
    for i in range(steps, 0, -1):
        r = radius * i / steps
        alpha = round(255 * (1 - i / steps) ** 1.6)
        draw.ellipse([center[0] - r, center[1] - r, center[0] + r, center[1] + r], fill=alpha)
    layer = Image.new("RGBA", (w, h), color[:3] + (0,))
    layer.putalpha(ImageChops.multiply(mask, Image.new("L", (w, h), color[3])))
    return layer


def tile_mask():
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([px(80), px(80), px(944), px(944)], radius=px(200), fill=255)
    return mask


def glyph_mask():
    """The G: an open ring, a bar into the middle and an arrow head on the open end."""
    mask = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(mask)
    cx, cy, r, w = px(512), px(532), px(228), px(98)
    end = 300  # degrees, clockwise from 3 o'clock
    d.arc([cx - r - w / 2, cy - r - w / 2, cx + r + w / 2, cy + r + w / 2], start=0, end=end, fill=255, width=w)
    # round cap where the ring meets the bar, and the bar itself
    d.ellipse([cx + r - w / 2, cy - w / 2, cx + r + w / 2, cy + w / 2], fill=255)
    bar_left = cx + px(36)
    d.rectangle([bar_left, cy - w / 2, cx + r, cy + w / 2], fill=255)
    d.ellipse([bar_left - w / 2, cy - w / 2, bar_left + w / 2, cy + w / 2], fill=255)
    # arrow head on the open end, pointing along the ring
    a = math.radians(end)
    px0, py0 = cx + r * math.cos(a), cy + r * math.sin(a)
    tx, ty = -math.sin(a), math.cos(a)
    nx, ny = ty, -tx
    tip = (px0 + 1.2 * w * tx, py0 + 1.2 * w * ty)
    base = (px0 - 0.3 * w * tx, py0 - 0.3 * w * ty)
    half = 1.12 * w
    d.polygon([tip, (base[0] + half * nx, base[1] + half * ny), (base[0] - half * nx, base[1] - half * ny)], fill=255)
    # soften the arrow's corners a little
    return mask.filter(ImageFilter.GaussianBlur(px(3))).point(lambda v: 255 if v > 128 else round(v * 2 * v / 255))


def compose() -> Image.Image:
    canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    tile = tile_mask()

    # soft shadow under the tile
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    shadow.putalpha(tile.point(lambda v: v * 0.45).filter(ImageFilter.GaussianBlur(px(22))))
    canvas.alpha_composite(shadow, (0, px(18)))

    # graphite body
    body = vertical_gradient((S, S), [(0.0, (78, 83, 93, 255)), (0.5, (44, 47, 54, 255)), (1.0, (20, 22, 26, 255))])
    body.alpha_composite(radial((S, S), (px(330), px(250)), px(620), (255, 255, 255, 36)))
    body.alpha_composite(radial((S, S), (px(512), px(560)), px(430), (120, 170, 255, 46)))
    body.putalpha(tile)
    canvas.alpha_composite(body)

    # the glyph: a soft dark shadow, silver glass, a bright upper edge
    glyph = glyph_mask()
    g_shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    g_shadow.putalpha(glyph.point(lambda v: v * 0.55).filter(ImageFilter.GaussianBlur(px(14))))
    canvas.alpha_composite(g_shadow, (0, px(14)))
    silver = vertical_gradient((S, S), [(0.0, (255, 255, 255, 255)), (0.45, (222, 226, 232, 255)), (1.0, (150, 157, 168, 255))])
    silver.putalpha(glyph)
    canvas.alpha_composite(silver)
    lower = Image.new("L", (S, S), 0)
    lower.paste(glyph, (0, px(7)))
    edge = ImageChops.subtract(glyph, lower).filter(ImageFilter.GaussianBlur(px(2)))
    shine = Image.new("RGBA", (S, S), (255, 255, 255, 0))
    shine.putalpha(edge)
    canvas.alpha_composite(shine)

    # glass gloss over the top half of the tile
    gloss_mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(gloss_mask).ellipse([px(-120), px(-520), px(1144), px(470)], fill=255)
    gloss_mask = ImageChops.multiply(gloss_mask.filter(ImageFilter.GaussianBlur(px(70))), tile)
    gloss = vertical_gradient((S, S), [(0.0, (255, 255, 255, 52)), (0.4, (255, 255, 255, 10)), (1.0, (255, 255, 255, 0))])
    gloss.putalpha(ImageChops.multiply(gloss.getchannel("A"), gloss_mask))
    canvas.alpha_composite(gloss)

    # thin bright rim, stronger at the top
    rim = Image.new("L", (S, S), 0)
    ImageDraw.Draw(rim).rounded_rectangle([px(80), px(80), px(944), px(944)], radius=px(200), outline=255, width=px(5))
    fade = vertical_gradient((S, S), [(0.0, (0, 0, 0, 150)), (0.5, (0, 0, 0, 40)), (1.0, (0, 0, 0, 70))]).getchannel("A")
    rim_layer = Image.new("RGBA", (S, S), (255, 255, 255, 0))
    rim_layer.putalpha(ImageChops.multiply(rim, fade))
    canvas.alpha_composite(rim_layer)
    return canvas.resize((1024, 1024), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    logo = compose()
    logo.save(OUT / "logo.png")
    logo.resize((256, 256), Image.LANCZOS).save(OUT / "logo-256.png")
    logo.save(OUT / "gupdater.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("written to", OUT)


if __name__ == "__main__":
    main()
