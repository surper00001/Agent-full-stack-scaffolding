"""图形验证码生成工具。"""

import io
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# 画布与字体参数（与前端展示高度 h-11 ≈ 44px 对齐）
_CAPTCHA_HEIGHT = 44
_FONT_SIZE = 30
_PADDING_X = 14
_PADDING_Y = 6
_CHAR_GAP = 8

_FONT_CANDIDATES = (
    "arial.ttf",
    "Arial.ttf",
    str(Path("C:/Windows/Fonts/arial.ttf")),
    str(Path("C:/Windows/Fonts/Arial.ttf")),
)


def _load_font() -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, _FONT_SIZE)
        except OSError:
            continue
    return ImageFont.load_default()


def _random_color(start: int = 0, end: int = 120) -> tuple[int, int, int]:
    return (random.randint(start, end), random.randint(start, end), random.randint(start, end))


def generate_captcha(code: str) -> bytes:
    """根据验证码字符串生成 PNG 图片字节（宽度按文字实际占位计算，保证 6 位完整可见）。"""
    code = str(code).strip()
    font = _load_font()

    measurer = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    glyphs: list[tuple[str, int, int, int]] = []
    x = _PADDING_X
    max_bottom = 0

    for i, ch in enumerate(code):
        bbox = measurer.textbbox((0, 0), ch, font=font)
        left, top, right, bottom = bbox
        char_w = right - left
        char_h = bottom - top
        glyphs.append((ch, x - left, top, char_w))
        x += char_w + (_CHAR_GAP if i < len(code) - 1 else 0)
        max_bottom = max(max_bottom, bottom - top)

    width = x + _PADDING_X
    height = max(_CAPTCHA_HEIGHT, max_bottom + _PADDING_Y * 2)

    img = Image.new("RGB", (width, height), (245, 247, 250))
    draw = ImageDraw.Draw(img)

    for _ in range(4):
        draw.line(
            [
                (random.randint(0, width), random.randint(0, height)),
                (random.randint(0, width), random.randint(0, height)),
            ],
            fill=_random_color(140, 200),
            width=1,
        )

    for _ in range(50):
        draw.point(
            (random.randint(0, width - 1), random.randint(0, height - 1)),
            fill=_random_color(120, 200),
        )

    baseline = _PADDING_Y
    for ch, draw_x, top, _char_w in glyphs:
        jitter_x = random.randint(-2, 2)
        jitter_y = random.randint(-2, 2)
        draw.text(
            (draw_x + jitter_x, baseline - top + jitter_y),
            ch,
            font=font,
            fill=_random_color(20, 100),
        )

    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
