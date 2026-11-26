"""Брендинг VPN-бота: аватар, баннер, промо и карточки тарифов.

Фоны лежат в vpn_brand/src (сгенерированы заранее), шрифты — в vpn_brand/fonts.
Скрипт накладывает на них текст и сохраняет готовые картинки в vpn_brand/.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

BASE = Path(__file__).resolve().parent
OUT = BASE / "vpn_brand"
SRC = OUT / "src"
FONTS = OUT / "fonts"

sys.path.insert(0, str(BASE))
from core import config  # noqa: E402

WHITE = (245, 247, 252)
SOFT = (196, 206, 230)
GREY = (132, 142, 172)
INK = (7, 9, 15)
CYAN = (58, 215, 255)
NAME = "БоссVPN"

ACCENTS = {
    "m1": (58, 215, 255),
    "m3": (139, 108, 255),
    "m6": (255, 178, 60),
    "y1": (46, 214, 118),
}
BADGES = {"m3": "ПОПУЛЯРНЫЙ", "m6": "ВЫГОДНО", "y1": "ЛУЧШАЯ ЦЕНА"}


def font(size: int, weight: str = "Bold", display: bool = False) -> ImageFont.FreeTypeFont:
    path = FONTS / ("Unbounded.ttf" if display else "Manrope.ttf")
    try:
        f = ImageFont.truetype(str(path), size)
        f.set_variation_by_name(weight)
        return f
    except Exception:
        fallback = "DejaVuSans-Bold.ttf" if weight in ("Bold", "ExtraBold", "Black") \
            else "DejaVuSans.ttf"
        for candidate in (f"/usr/share/fonts/truetype/dejavu/{fallback}",
                          "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf"):
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                continue
    return ImageFont.load_default()


def cover(img: Image.Image, w: int, h: int, focus_x: float = 0.5) -> Image.Image:
    """Масштабирует и обрезает картинку под размер w×h."""
    scale = max(w / img.width, h / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left = int((img.width - w) * focus_x)
    top = (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def shade(img: Image.Image, strength: int = 230, width: float = 0.6) -> Image.Image:
    """Затемнение слева, чтобы текст читался."""
    w, h = img.size
    grad = Image.new("L", (w, 1))
    for x in range(w):
        t = max(0.0, 1 - x / (w * width))
        grad.putpixel((x, 0), int(strength * t ** 1.4))
    mask = grad.resize((w, h))
    dark = Image.new("RGB", (w, h), INK)
    return Image.composite(dark, img.convert("RGB"), mask)


def tint(img: Image.Image, color: tuple[int, int, int]) -> Image.Image:
    """Перекрашивает нейтральный фон в цвет акцента."""
    gray = ImageEnhance.Brightness(img.convert("L")).enhance(1.15)
    layer = Image.new("RGB", img.size, color)
    colored = ImageChops.multiply(Image.merge("RGB", (gray, gray, gray)), layer)
    return Image.blend(img.convert("RGB"), colored, 0.85)


def glow_text(img: Image.Image, xy, text, fnt, fill, glow, radius=18) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(xy, text, font=fnt, fill=glow + (190,))
    layer = layer.filter(ImageFilter.GaussianBlur(radius))
    img.alpha_composite(layer)
    ImageDraw.Draw(img).text(xy, text, font=fnt, fill=fill)


def glass(img: Image.Image, box, radius: int, alpha: int = 34, border=(255, 255, 255, 46)):
    x0, y0, x1, y1 = box
    region = img.crop(box).filter(ImageFilter.GaussianBlur(24))
    mask = Image.new("L", region.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, x1 - x0 - 1, y1 - y0 - 1], radius, fill=255)
    img.paste(region, (x0, y0), mask)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle(box, radius, fill=(255, 255, 255, alpha), outline=border, width=2)
    img.alpha_composite(layer)


def pill(img: Image.Image, xy, text: str, fnt, bg, fg, pad=(26, 12), radius=None) -> int:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    l, t, r, b = d.textbbox((0, 0), text, font=fnt)
    w, h = r - l + pad[0] * 2, b - t + pad[1] * 2
    x, y = xy
    d.rounded_rectangle([x, y, x + w, y + h], radius or h // 2, fill=bg)
    img.alpha_composite(layer)
    ImageDraw.Draw(img).text((x + pad[0] - l, y + pad[1] - t), text, font=fnt, fill=fg)
    return w


def icon(d: ImageDraw.ImageDraw, kind: str, cx: int, cy: int, r: int, color) -> None:
    """Простые векторные иконки (эмодзи шрифты не рисуют)."""
    w = max(3, r // 6)
    if kind == "calendar":
        d.rounded_rectangle([cx - r, cy - r * 0.8, cx + r, cy + r], r // 4, outline=color, width=w)
        d.line([cx - r, cy - r * 0.3, cx + r, cy - r * 0.3], fill=color, width=w)
        for dx in (-0.45, 0.45):
            d.line([cx + r * dx, cy - r * 1.1, cx + r * dx, cy - r * 0.55], fill=color, width=w)
    elif kind == "data":
        for i, hgt in enumerate((0.5, 1.0, 1.5)):
            x = cx - r + i * r * 0.8
            d.rounded_rectangle([x, cy + r - r * hgt * 1.3, x + r * 0.5, cy + r], 3, fill=color)
    elif kind == "devices":
        d.rounded_rectangle([cx - r * 0.55, cy - r, cx + r * 0.55, cy + r], r // 4,
                            outline=color, width=w)
        d.line([cx - r * 0.15, cy + r * 0.7, cx + r * 0.15, cy + r * 0.7], fill=color, width=w)
    elif kind == "bolt":
        d.polygon([(cx + r * 0.2, cy - r), (cx - r * 0.6, cy + r * 0.15), (cx - r * 0.05, cy + r * 0.15),
                   (cx - r * 0.2, cy + r), (cx + r * 0.6, cy - r * 0.15), (cx + r * 0.05, cy - r * 0.15)],
                  fill=color)


def avatar(size: int = 512) -> Image.Image:
    img = cover(Image.open(SRC / "emblem.png").convert("RGB"), size, size)
    img = ImageEnhance.Contrast(img).enhance(1.08)
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size * 4 - 1, size * 4 - 1], fill=255)
    mask = mask.resize((size, size), Image.LANCZOS)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def banner(w: int = 1280, h: int = 640) -> Image.Image:
    img = shade(cover(Image.open(SRC / "hero.png"), w, h, focus_x=0.85), 235, 0.62)
    img = img.convert("RGBA")
    left = int(w * 0.065)
    pill(img, (left, int(h * 0.15)), "VPN БЕЗ ЛОГОВ", font(22, "Bold"),
         (58, 215, 255, 40), CYAN, pad=(20, 10))
    glow_text(img, (left, int(h * 0.26)), NAME, font(int(h * 0.15), "Bold", True),
              WHITE, CYAN, 26)
    d = ImageDraw.Draw(img)
    d.text((left, int(h * 0.50)), "Быстрый. Стабильный. Твой.",
           font=font(int(h * 0.058), "SemiBold"), fill=SOFT)
    price = min(p["price"] for p in config.PLANS)
    x = left
    for chip in ("iOS", "Android", "Windows"):
        x += pill(img, (x, int(h * 0.65)), chip, font(24, "SemiBold"),
                  (255, 255, 255, 22), WHITE, pad=(22, 12)) + 12
    pill(img, (left, int(h * 0.79)), f"от {price} ₽ / мес", font(32, "ExtraBold"),
         CYAN, INK, pad=(30, 14))
    return img.convert("RGB")


def promo(size: int = 1080) -> Image.Image:
    hero = Image.open(SRC / "hero.png").convert("RGB")
    hero = hero.resize((round(hero.width * 720 / hero.height), 720), Image.LANCZOS)
    img = Image.new("RGBA", (size, size), INK + (255,))
    fade = Image.linear_gradient("L").resize(hero.size).point(lambda v: min(255, v * 3))
    img.paste(hero, (size - hero.width, size - hero.height), fade)
    pill(img, (80, 90), "ПОДКЛЮЧЕНИЕ ЗА 2 МИНУТЫ", font(26, "Bold"),
         (58, 215, 255, 40), CYAN, pad=(22, 12))
    glow_text(img, (80, 170), NAME, font(116, "Bold", True), WHITE, CYAN, 30)
    d = ImageDraw.Draw(img)
    d.text((82, 330), "быстрый VPN", font=font(60, "ExtraBold"), fill=CYAN)
    d.text((82, 400), "без логов и тормозов", font=font(60, "SemiBold"), fill=WHITE)
    y = 560
    for plan in config.PLANS:
        pill(img, (80, y), f"{plan['title']} · {plan['price']} ₽", font(30, "Bold"),
             (255, 255, 255, 30), WHITE, pad=(26, 14))
        y += 84
    return img.convert("RGB")


def plan_card(plan: dict, size: int = 1080) -> Image.Image:
    accent = ACCENTS.get(plan["code"], CYAN)
    img = tint(Image.open(SRC / "card_bg.png"), accent)
    img = cover(img, size, size).convert("RGBA")
    d = ImageDraw.Draw(img)

    d.text((90, 92), NAME, font=font(34, "Bold", True), fill=SOFT)
    if plan["code"] in BADGES:
        fnt = font(24, "ExtraBold")
        bw = d.textbbox((0, 0), BADGES[plan["code"]], font=fnt)[2] + 52
        pill(img, (size - 90 - bw, 88), BADGES[plan["code"]], fnt, accent, INK)

    glow_text(img, (86, 190), plan["title"], font(96, "Bold", True), WHITE, accent, 30)
    per_month = round(plan["price"] / max(1, plan["days"] / 30))
    d = ImageDraw.Draw(img)
    d.text((90, 330), f"≈ {per_month} ₽ в месяц", font=font(40, "SemiBold"), fill=SOFT)

    box = (80, 420, size - 80, 790)
    glass(img, box, 40)
    d = ImageDraw.Draw(img)
    rows = [("calendar", f"{plan['days']} дней доступа"),
            ("data", f"{plan.get('gb', 0)} ГБ трафика"),
            ("devices", f"до {plan.get('devices', 1)} устройств"),
            ("bolt", "VLESS · REALITY")]
    y = box[1] + 46
    for kind, label in rows:
        d.ellipse([130, y - 2, 194, y + 62], fill=tuple(int(c * 0.25 + 12) for c in accent))
        icon(d, kind, 162, y + 30, 16, accent)
        d.text((222, y + 6), label, font=font(42, "SemiBold"), fill=WHITE)
        y += 82

    price = f"{plan['price']} ₽"
    fnt = font(92, "Bold", True)
    pw = d.textbbox((0, 0), price, font=fnt)
    px, py = 80, 840
    d.rounded_rectangle([px, py, px + pw[2] - pw[0] + 100, py + 160], 44, fill=accent)
    d.text((px + 50 - pw[0], py + 80 - (pw[1] + pw[3]) // 2), price, font=fnt, fill=INK)
    d.text((px + pw[2] - pw[0] + 140, py + 52), "за весь", font=font(36, "SemiBold"), fill=SOFT)
    d.text((px + pw[2] - pw[0] + 140, py + 96), "период", font=font(36, "SemiBold"), fill=SOFT)
    return img.convert("RGB")


def main() -> None:
    avatar(512).save(OUT / "avatar_512.png")
    banner(1280, 640).save(OUT / "banner_1280x640.png")
    promo(1080).save(OUT / "promo_1080.png")
    for plan in config.PLANS:
        plan_card(plan).save(config.plan_image(plan["code"]))
    print("готово:", [p.name for p in sorted(OUT.glob("*.png"))])


if __name__ == "__main__":
    main()
