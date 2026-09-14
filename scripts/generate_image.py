"""
GymMatch向けのブランド画像（フィード投稿用 1:1 / ストーリー用 9:16）を生成する。

使い方:
    from generate_image import make_feed_image, make_story_image
    make_feed_image(content_item, "out/feed.png")
    make_story_image(content_item, "out/story.png")

フォントは assets/fonts/NotoSansJP-Variable.ttf を使用する（可変フォント、
weight軸で Regular/Bold を切り替え）。GitHub Actions 上ではワークフローが
このフォントを実行時にダウンロードする想定。
"""
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = os.environ.get(
    "GYMMATCH_FONT_PATH",
    os.path.join(HERE, "..", "assets", "fonts", "NotoSansJP-Variable.ttf"),
)

# ブランドカラー（オレンジ系）
COLOR_TOP = (255, 141, 66)      # 明るいオレンジ
COLOR_BOTTOM = (232, 89, 12)    # 濃いオレンジ
COLOR_WHITE = (255, 255, 255)
COLOR_BADGE_BG = (255, 255, 255, 60)
COLOR_SHADOW = (0, 0, 0, 70)


def _font(size, weight=400):
    f = ImageFont.truetype(FONT_PATH, size)
    try:
        f.set_variation_by_axes([weight])
    except Exception:
        pass
    return f


def _vertical_gradient(size, top, bottom):
    w, h = size
    base = Image.new("RGB", (1, h), color=0)
    for y in range(h):
        t = y / max(h - 1, 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        base.putpixel((0, y), (r, g, b))
    return base.resize((w, h))


def _wrap_by_width(draw, text, font, max_width):
    """日本語は単語区切りがないので、1文字ずつ幅を測って折り返す。
    text 中の改行 (\n) は明示的な改行として尊重する。"""
    lines = []
    for paragraph in text.split("\n"):
        if paragraph == "":
            lines.append("")
            continue
        current = ""
        for ch in paragraph:
            trial = current + ch
            w = draw.textlength(trial, font=font)
            if w > max_width and current:
                lines.append(current)
                current = ch
            else:
                current = trial
        lines.append(current)
    return lines


def _draw_rounded_rect(draw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def _draw_wordmark(draw, pos, font):
    x, y = pos
    # 簡易ダンベルアイコン
    bar_y = y + 18
    draw.rounded_rectangle([x, bar_y - 4, x + 34, bar_y + 4], radius=4, fill=COLOR_WHITE)
    draw.ellipse([x - 10, bar_y - 14, x + 6, bar_y + 14], fill=COLOR_WHITE)
    draw.ellipse([x + 28, bar_y - 14, x + 44, bar_y + 14], fill=COLOR_WHITE)
    draw.text((x + 54, y), "GymMatch", font=font, fill=COLOR_WHITE)


def _draw_badge(draw, top_right, text, font):
    pad_x, pad_y = 22, 12
    w = draw.textlength(text, font=font)
    h = font.size
    x2, y1 = top_right
    box = [x2 - w - pad_x * 2, y1, x2, y1 + h + pad_y * 2]
    overlay_layer = Image.new("RGBA", (int(box[2] - box[0]), int(box[3] - box[1])), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay_layer)
    odraw.rounded_rectangle([0, 0, overlay_layer.width, overlay_layer.height], radius=overlay_layer.height // 2, fill=(255, 255, 255, 70))
    return box, overlay_layer, (box[0] + pad_x, box[1] + pad_y)


def _compose(size, item, headline_size, body_size, tag_font_size, wordmark_size,
             content_top, content_width, handle=True, top_safe=None, bottom_safe=None):
    img = _vertical_gradient(size, COLOR_TOP, COLOR_BOTTOM).convert("RGBA")
    draw = ImageDraw.Draw(img)
    w, h = size
    margin = int(w * 0.09)
    if top_safe is None:
        top_safe = margin
    if bottom_safe is None:
        bottom_safe = margin

    # ワードマーク（左上）
    _draw_wordmark(draw, (margin, top_safe), _font(wordmark_size, 700))

    # タグバッジ（右上）
    tag_font = _font(tag_font_size, 600)
    box, overlay_layer, text_pos = _draw_badge(draw, (w - margin, top_safe - 4), item["tag"], tag_font)
    img.alpha_composite(overlay_layer, (int(box[0]), int(box[1])))
    draw = ImageDraw.Draw(img)
    draw.text(text_pos, item["tag"], font=tag_font, fill=COLOR_WHITE)

    # 見出し
    headline_font = _font(headline_size, 800)
    y = content_top
    for line in item["headline"].split("\n"):
        draw.text((margin, y), line, font=headline_font, fill=COLOR_WHITE)
        bbox = draw.textbbox((margin, y), line, font=headline_font)
        y = bbox[3] + int(headline_size * 0.18)

    y += int(headline_size * 0.35)

    # 本文
    body_font = _font(body_size, 500)
    for line in _wrap_by_width(draw, item["body"], body_font, content_width):
        draw.text((margin, y), line, font=body_font, fill=(255, 245, 235))
        bbox = draw.textbbox((margin, y), line or " ", font=body_font)
        y = bbox[3] + int(body_size * 0.28)

    if handle:
        handle_font = _font(int(w * 0.028), 600)
        text = "@gymmatchapp"
        tw = draw.textlength(text, font=handle_font)
        draw.text((w - margin - tw, h - bottom_safe - handle_font.size), text, font=handle_font, fill=(255, 255, 255, 200))

    return img.convert("RGB")


def make_feed_image(item, out_path):
    size = (1080, 1080)
    img = _compose(
        size, item,
        headline_size=78, body_size=34, tag_font_size=28, wordmark_size=34,
        content_top=int(size[1] * 0.34), content_width=size[0] - int(size[0] * 0.18) * 1.0 - 40,
    )
    img.save(out_path, "PNG")
    return out_path


def make_story_image(item, out_path):
    size = (1080, 1920)
    img = _compose(
        size, item,
        headline_size=84, body_size=36, tag_font_size=30, wordmark_size=36,
        content_top=int(size[1] * 0.38), content_width=size[0] - int(size[0] * 0.18) * 1.0 - 40,
        top_safe=int(size[1] * 0.12), bottom_safe=int(size[1] * 0.14),
    )
    img.save(out_path, "PNG")
    return out_path


if __name__ == "__main__":
    import json
    with open(os.path.join(HERE, "..", "content", "content.json"), encoding="utf-8") as f:
        item = json.load(f)["items"][0]
    os.makedirs("/tmp/gm_preview", exist_ok=True)
    make_feed_image(item, "/tmp/gm_preview/feed.png")
    make_story_image(item, "/tmp/gm_preview/story.png")
    print("saved previews to /tmp/gm_preview")
