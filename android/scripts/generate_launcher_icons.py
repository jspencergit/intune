"""Generate Android launcher mipmaps from repo-root IntuneLogo.png."""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "IntuneLogo.png"
RES = ROOT / "android" / "app" / "src" / "main" / "res"

# Adaptive layer (108dp) and legacy full icon (48dp) per density
DENSITIES = {
    "mdpi": (108, 48),
    "hdpi": (162, 72),
    "xhdpi": (216, 96),
    "xxhdpi": (324, 144),
    "xxxhdpi": (432, 192),
}


def trim_near_white(im: Image.Image, thresh: int = 250) -> Image.Image:
    px = im.load()
    w, h = im.size
    left, top, right, bottom = w, h, 0, 0
    found = False
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 10:
                continue
            if r < thresh or g < thresh or b < thresh:
                found = True
                left = min(left, x)
                top = min(top, y)
                right = max(right, x)
                bottom = max(bottom, y)
    if not found:
        return im
    pad = max(2, int(min(w, h) * 0.02))
    left = max(0, left - pad)
    top = max(0, top - pad)
    right = min(w - 1, right + pad)
    bottom = min(h - 1, bottom + pad)
    return im.crop((left, top, right + 1, bottom + 1))


def fit_center(logo_img: Image.Image, canvas_size: int, scale: float = 0.64) -> Image.Image:
    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    target = int(canvas_size * scale)
    lw, lh = logo_img.size
    ratio = min(target / lw, target / lh)
    nw, nh = max(1, int(lw * ratio)), max(1, int(lh * ratio))
    resized = logo_img.resize((nw, nh), Image.Resampling.LANCZOS)
    x = (canvas_size - nw) // 2
    y = (canvas_size - nh) // 2
    canvas.paste(resized, (x, y), resized)
    return canvas


def solid_bg(size: int, color=(255, 255, 255, 255)) -> Image.Image:
    return Image.new("RGBA", (size, size), color)


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"Missing logo: {SRC}")

    logo = trim_near_white(Image.open(SRC).convert("RGBA"))

    for dens, (layer, legacy) in DENSITIES.items():
        mip = RES / f"mipmap-{dens}"
        mip.mkdir(parents=True, exist_ok=True)

        bg = solid_bg(layer)
        fg = fit_center(logo, layer, scale=0.64)
        bg.save(mip / "ic_launcher_background.png", "PNG")
        fg.save(mip / "ic_launcher_foreground.png", "PNG")

        leg = solid_bg(legacy)
        leg_logo = fit_center(logo, legacy, scale=0.78)
        leg.paste(leg_logo, (0, 0), leg_logo)
        leg.save(mip / "ic_launcher.png", "PNG")
        leg.save(mip / "ic_launcher_round.png", "PNG")

    anydpi = RES / "mipmap-anydpi-v26"
    anydpi.mkdir(parents=True, exist_ok=True)
    adaptive = """<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@mipmap/ic_launcher_background"/>
    <foreground android:drawable="@mipmap/ic_launcher_foreground"/>
</adaptive-icon>
"""
    (anydpi / "ic_launcher.xml").write_text(adaptive, encoding="utf-8")
    (anydpi / "ic_launcher_round.xml").write_text(adaptive, encoding="utf-8")

    store = ROOT / "android" / "store"
    store.mkdir(parents=True, exist_ok=True)
    play = solid_bg(512)
    play_logo = fit_center(logo, 512, scale=0.82)
    play.paste(play_logo, (0, 0), play_logo)
    play.save(store / "play_icon_512.png", "PNG")

    print(f"OK: icons from {SRC.name}")
    print(f"  Play 512: {store / 'play_icon_512.png'}")


if __name__ == "__main__":
    main()
