"""Брендинг VPN-бота: аватар, баннер, промо."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path("vpn_brand")
OUT.mkdir(exist_ok=True)

BLACK = (8, 10, 16)
CYAN = (58, 215, 255)
LIME = (200, 255, 61)
WHITE = (245, 247, 252)
GREY = (140, 148, 175)
NAME = "БОСС"
TAG = "VPN как у босса"


def font(size: int, bold: bool = True):
    path = "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"
    for candidate in (path, "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def bg(w: int, h: int, top=(8, 10, 18), bottom=(16, 34, 58)) -> Image.Image:
    img = Image.new("RGB", (w, h), top)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)],
               fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([w * 0.5, -h * 0.5, w * 1.4, h * 0.9], fill=(30, 150, 200, 170))
    gd.ellipse([-w * 0.3, h * 0.4, w * 0.6, h * 1.5], fill=(90, 60, 210, 140))
    glow = glow.filter(ImageFilter.GaussianBlur(int(w * 0.08)))
    return Image.alpha_composite(img.convert("RGBA"), glow)


def shield(d: ImageDraw.ImageDraw, cx: int, cy: int, r: int, color=CYAN) -> None:
    """Щит с молнией."""
    top = [(cx - r, cy - r * 0.75), (cx, cy - r), (cx + r, cy - r * 0.75)]
    body = [(cx + r, cy - r * 0.55), (cx + r * 0.85, cy + r * 0.35),
            (cx, cy + r), (cx - r * 0.85, cy + r * 0.35), (cx - r, cy - r * 0.55)]
    d.polygon(top + body, outline=color, width=max(3, r // 22))
    bolt = [(cx + r * 0.12, cy - r * 0.55), (cx - r * 0.22, cy + r * 0.06),
            (cx + r * 0.02, cy + r * 0.06), (cx - r * 0.10, cy + r * 0.55),
            (cx + r * 0.28, cy - r * 0.10), (cx + r * 0.03, cy - r * 0.10)]
    d.polygon(bolt, fill=color)


def avatar(size: int = 512) -> Image.Image:
    img = bg(size, size, (7, 9, 15), (14, 40, 66))
    d = ImageDraw.Draw(img)
    shield(d, size // 2, size // 2 + 10, int(size * 0.30))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def banner(w: int = 1280, h: int = 640) -> Image.Image:
    img = bg(w, h, (7, 9, 15), (16, 44, 72))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, 8], fill=CYAN)
    left = int(w * 0.06)
    d.text((left, int(h * 0.16)), NAME, font=font(int(h * 0.24)), fill=WHITE)
    d.rectangle([left + 4, int(h * 0.47), left + 130, int(h * 0.47) + 8], fill=CYAN)
    d.text((left, int(h * 0.53)), TAG, font=font(int(h * 0.075), bold=False), fill=(200, 215, 240))
    d.text((left, int(h * 0.68)), "2 минуты на настройку · iOS · Android · Windows",
           font=font(int(h * 0.055), bold=False), fill=GREY)
    shield(d, int(w * 0.80), int(h * 0.50), int(h * 0.26))
    # узлы сети
    for i, (dx, dy) in enumerate([(-.13, -.28), (.12, -.30), (-.16, .26), (.15, .28)]):
        x = int(w * 0.80 + w * dx)
        y = int(h * 0.50 + h * dy)
        d.ellipse([x - 7, y - 7, x + 7, y + 7], fill=LIME if i % 2 else CYAN)
    return img.convert("RGB")


def promo(size: int = 1080) -> Image.Image:
    img = bg(size, size, (7, 9, 15), (14, 40, 66))
    d = ImageDraw.Draw(img)
    d.text((70, 120), NAME, font=font(120), fill=WHITE)
    d.text((72, 270), "быстрый VPN", font=font(64, bold=False), fill=CYAN)
    d.text((72, 350), "без логов и тормозов", font=font(64, bold=False), fill=WHITE)
    shield(d, size // 2, int(size * 0.63), 190)
    d.text((72, size - 150), "1 месяц · 3 месяца · год", font=font(44), fill=GREY)
    return img.convert("RGB")


def main() -> None:
    avatar(512).save(OUT / "avatar_512.png")
    banner(1280, 640).save(OUT / "banner_1280x640.png")
    promo(1080).save(OUT / "promo_1080.png")
    print("готово:", [p.name for p in sorted(OUT.glob("*.png"))])


if __name__ == "__main__":
    main()
