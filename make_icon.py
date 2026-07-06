"""Generate a fantastic app icon (icon.ico / icon.png) with the wordmark "TYLT".

Layered, supersampled render:
  * squircle badge with a multi-stop diagonal gradient (indigo -> violet -> pink)
  * two soft radial glows for depth
  * inner stroke + glossy top sheen for a glassy look
  * "TYLT" laid out 2x2, with a soft drop shadow and a subtle vertical sheen

Run:  python make_icon.py
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

SS = 4               # supersampling factor
OUT = 512            # final master size
M = OUT * SS         # working (supersampled) size
RADIUS = int(0.24 * M)

# gradient colour stops (position 0..1, RGB) — deep, saturated, vivid
STOPS = [
    (0.00, (32, 26, 120)),    # deep indigo
    (0.35, (86, 40, 220)),    # electric violet
    (0.65, (162, 38, 210)),   # magenta
    (0.85, (224, 52, 150)),   # hot pink
    (1.00, (255, 120, 90)),   # coral flare
]


def _font(size: int):
    for name in ("segoeuib.ttf", "arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _diagonal_gradient(size: int) -> Image.Image:
    """Smooth multi-stop gradient running top-left -> bottom-right."""
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float32)
    t = (xs + ys) / (2 * (size - 1))          # 0 at TL, 1 at BR
    pos = np.array([s[0] for s in STOPS], dtype=np.float32)
    cols = np.array([s[1] for s in STOPS], dtype=np.float32)
    rgb = np.stack(
        [np.interp(t, pos, cols[:, c]) for c in range(3)], axis=-1
    ).astype(np.uint8)
    return Image.fromarray(rgb, "RGB")


def _radial_glow(size: int, cx: float, cy: float, radius: float, strength: int):
    """A soft white radial blob (alpha) used to add highlights."""
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float32)
    d = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2) / radius
    a = np.clip(1.0 - d, 0.0, 1.0) ** 2 * strength
    return Image.fromarray(a.astype(np.uint8), "L")


def _squircle_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=radius, fill=255
    )
    return mask


def build_master() -> Image.Image:
    badge = Image.new("RGBA", (M, M), (0, 0, 0, 0))

    # base gradient
    grad = _diagonal_gradient(M).convert("RGBA")
    badge = Image.alpha_composite(badge, grad)

    # small bright sparkle top-left for a glassy catch-light (keeps colour)
    sparkle = Image.composite(
        Image.new("RGBA", (M, M), (255, 255, 255, 255)),
        Image.new("RGBA", (M, M), (255, 255, 255, 0)),
        _radial_glow(M, 0.26 * M, 0.20 * M, 0.30 * M, 70),
    )
    badge = Image.alpha_composite(badge, sparkle)

    # gentle vignette: darken only the far corners so letters pop, colour stays
    vig = _radial_glow(M, M / 2, M / 2, M * 0.85, 255)
    dark = Image.new("RGBA", (M, M), (8, 4, 30, 0))
    dark.putalpha(Image.eval(vig, lambda a: 80 - int(a * 80 / 255)))
    badge = Image.alpha_composite(badge, dark)

    draw = ImageDraw.Draw(badge)

    # inner stroke for crisp definition
    inset = int(0.018 * M)
    draw.rounded_rectangle(
        [inset, inset, M - 1 - inset, M - 1 - inset],
        radius=RADIUS - inset,
        outline=(255, 255, 255, 70),
        width=max(2, int(0.008 * M)),
    )

    # glossy top sheen: a bright, soft band across the upper third
    sheen = Image.new("RGBA", (M, M), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sheen)
    sd.ellipse([-0.15 * M, -0.55 * M, 1.15 * M, 0.42 * M], fill=(255, 255, 255, 46))
    sheen = sheen.filter(ImageFilter.GaussianBlur(M * 0.02))
    badge = Image.alpha_composite(badge, sheen)

    # letters (2x2) — drop shadow then white glyphs with a faint vertical sheen
    font = _font(int(0.40 * M))
    quad = M / 2
    cells = [("T", 0), ("Y", 1), ("L", 2), ("T", 3)]

    text_layer = Image.new("RGBA", (M, M), (0, 0, 0, 0))
    td = ImageDraw.Draw(text_layer)
    for ch, idx in cells:
        col, row = idx % 2, idx // 2
        cx = col * quad + quad / 2
        cy = row * quad + quad / 2
        bb = td.textbbox((0, 0), ch, font=font)
        w, h = bb[2] - bb[0], bb[3] - bb[1]
        td.text((cx - w / 2 - bb[0], cy - h / 2 - bb[1]), ch, font=font, fill=(255, 255, 255, 255))

    shadow = text_layer.filter(ImageFilter.GaussianBlur(M * 0.012))
    shadow = Image.eval(shadow, lambda v: v)  # keep alpha
    # offset + darken the shadow
    shadow_col = Image.new("RGBA", (M, M), (12, 4, 40, 255))
    shadow_col.putalpha(shadow.split()[3].point(lambda a: int(a * 0.75)))
    off = int(0.013 * M)
    badge.alpha_composite(shadow_col, (off, off))
    badge = Image.alpha_composite(badge, text_layer)

    # clip everything to the squircle
    out = Image.new("RGBA", (M, M), (0, 0, 0, 0))
    out.paste(badge, (0, 0), _squircle_mask(M, RADIUS))
    return out.resize((OUT, OUT), Image.LANCZOS)


def _with_shadow(master: Image.Image) -> Image.Image:
    """256px PNG with a soft drop shadow under the badge (for readmes)."""
    pad = 28
    canvas = Image.new("RGBA", (OUT + pad * 2, OUT + pad * 2), (0, 0, 0, 0))
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sh.paste((0, 0, 0, 130), (pad, pad + 12), master.split()[3])
    sh = sh.filter(ImageFilter.GaussianBlur(18))
    canvas = Image.alpha_composite(canvas, sh)
    canvas.alpha_composite(master, (pad, pad))
    return canvas.resize((256, 256), Image.LANCZOS)


def main():
    master = build_master()
    sizes = [16, 24, 32, 48, 64, 128, 256]
    master.save("icon.ico", sizes=[(s, s) for s in sizes])
    master.resize((256, 256), Image.LANCZOS).save("icon.png")
    _with_shadow(master).save("icon_shadow.png")
    print("Wrote icon.ico, icon.png, icon_shadow.png")


if __name__ == "__main__":
    main()
