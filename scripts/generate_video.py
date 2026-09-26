"""
GymMatch向けのリール(Reels)用ショート動画を生成する（1080x1920、約7秒、MP4）。

外部AI動画生成サービスは使わず、Pillowで1コマずつ描画したフレームを
ffmpegでエンコードすることで、無料で「タイプライター風に見出しが現れる →
本文がフェードイン → 光のシマーが流れる」という簡単なモーショングラフィック
動画を作る。

使い方:
    from generate_video import make_reel_video
    make_reel_video(content_item, "out/reel.mp4")

前提: システムに ffmpeg がインストールされていること
（GitHub Actionsのワークフロー側で `apt-get install -y ffmpeg` する）。
"""
import math
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from generate_image import (  # noqa: E402
    COLOR_TOP, COLOR_BOTTOM, COLOR_WHITE,
    _font, _vertical_gradient, _wrap_by_width, _draw_wordmark, _draw_badge,
)

SIZE = (1080, 1920)
FPS = 30
DURATION_SEC = 7
TOTAL_FRAMES = FPS * DURATION_SEC

MARGIN = int(SIZE[0] * 0.09)
TOP_SAFE = int(SIZE[1] * 0.12)
BOTTOM_SAFE = int(SIZE[1] * 0.14)
CONTENT_TOP = int(SIZE[1] * 0.40)
CONTENT_WIDTH = SIZE[0] - MARGIN * 2

HEADLINE_SIZE = 84
BODY_SIZE = 38
TAG_SIZE = 30
WORDMARK_SIZE = 36

# タイムライン（フレーム数）
HEADLINE_START = 6
HEADLINE_DURATION = 78          # 見出しがタイプライターで表示され終わるまで
BODY_FADE_START = HEADLINE_START + HEADLINE_DURATION + 8
BODY_FADE_DURATION = 18
END_HOLD_START = BODY_FADE_START + BODY_FADE_DURATION + 20  # CTA表示開始


def _ease_out(t):
    return 1 - (1 - t) ** 2


def _static_base():
    """毎フレーム共通の背景（グラデーション + ワードマーク + タグバッジ）を
    1枚だけ作って使い回す。"""
    img = _vertical_gradient(SIZE, COLOR_TOP, COLOR_BOTTOM).convert("RGBA")
    draw = ImageDraw.Draw(img)
    _draw_wordmark(draw, (MARGIN, TOP_SAFE), _font(WORDMARK_SIZE, 700))
    return img


def _headline_lines(item):
    return item["headline"].split("\n")


def _total_headline_chars(lines):
    return sum(len(l) for l in lines)


def _shimmer_layer(frame_idx, total_frames):
    """左上から右下へゆっくり流れる、淡い光の帯。動画に"動いている感"を出す。"""
    layer = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    progress = (frame_idx / total_frames)
    band_w = 260
    # 帯の中心位置（画面の外から外へ、斜めに通過）
    span = SIZE[0] + SIZE[1] + band_w * 2
    center = -band_w + progress * span
    for dx in range(-band_w, band_w, 4):
        alpha = max(0, int(26 * (1 - abs(dx) / band_w)))
        if alpha <= 0:
            continue
        x = center + dx
        d.line([(x, SIZE[1]), (x - SIZE[1], 0)], fill=(255, 255, 255, alpha), width=4)
    return layer


def _compose_frame(item, base, frame_idx, tag_font, headline_font, body_font, handle_font, body_lines):
    img = base.copy()

    # シマー（背景の上、テキストの下）
    img.alpha_composite(_shimmer_layer(frame_idx, TOTAL_FRAMES))

    draw = ImageDraw.Draw(img)

    # タグバッジ（開始直後にふわっと表示）
    tag_alpha = min(255, max(0, int(255 * (frame_idx / 10))))
    if tag_alpha > 0:
        box, overlay_layer, text_pos = _draw_badge(draw, (SIZE[0] - MARGIN, TOP_SAFE - 4), item["tag"], tag_font)
        tinted = overlay_layer.copy()
        r, g, b, a = tinted.split()
        a = a.point(lambda v: int(v * tag_alpha / 255))
        tinted = Image.merge("RGBA", (r, g, b, a))
        img.alpha_composite(tinted, (int(box[0]), int(box[1])))
        draw = ImageDraw.Draw(img)
        text_layer = Image.new("RGBA", SIZE, (0, 0, 0, 0))
        td = ImageDraw.Draw(text_layer)
        td.text(text_pos, item["tag"], font=tag_font, fill=(255, 255, 255, tag_alpha))
        img.alpha_composite(text_layer)
        draw = ImageDraw.Draw(img)

    # 見出し（タイプライター表示）
    lines = _headline_lines(item)
    total_chars = _total_headline_chars(lines)
    chars_elapsed = 0
    if frame_idx >= HEADLINE_START:
        t = min(1.0, (frame_idx - HEADLINE_START) / HEADLINE_DURATION)
        chars_elapsed = int(_ease_out(t) * total_chars)

    y = CONTENT_TOP
    remaining = chars_elapsed
    for line in lines:
        shown = line[:max(0, remaining)]
        remaining -= len(line)
        if shown:
            draw.text((MARGIN, y), shown, font=headline_font, fill=COLOR_WHITE)
        bbox = draw.textbbox((MARGIN, y), line or " ", font=headline_font)
        y = bbox[3] + int(HEADLINE_SIZE * 0.18)
    y += int(HEADLINE_SIZE * 0.35)

    # 本文（フェードイン）
    body_alpha = 0
    if frame_idx >= BODY_FADE_START:
        t = min(1.0, (frame_idx - BODY_FADE_START) / BODY_FADE_DURATION)
        body_alpha = int(255 * t)
    if body_alpha > 0:
        text_layer = Image.new("RGBA", SIZE, (0, 0, 0, 0))
        td = ImageDraw.Draw(text_layer)
        by = y
        for line in body_lines:
            td.text((MARGIN, by), line, font=body_font, fill=(255, 245, 235, body_alpha))
            bbox = td.textbbox((MARGIN, by), line or " ", font=body_font)
            by = bbox[3] + int(BODY_SIZE * 0.28)
        img.alpha_composite(text_layer)

    # ハンドル（終盤でふわっと表示、CTA的に）
    handle_alpha = 0
    if frame_idx >= END_HOLD_START:
        t = min(1.0, (frame_idx - END_HOLD_START) / 15)
        handle_alpha = int(255 * t)
    if handle_alpha > 0:
        text_layer = Image.new("RGBA", SIZE, (0, 0, 0, 0))
        td = ImageDraw.Draw(text_layer)
        text = "@gymmatchapp をフォロー"
        tw = td.textlength(text, font=handle_font)
        td.text(((SIZE[0] - tw) / 2, SIZE[1] - BOTTOM_SAFE - handle_font.size), text,
                font=handle_font, fill=(255, 255, 255, handle_alpha))
        img.alpha_composite(text_layer)

    return img.convert("RGB")


def make_reel_video(item, out_path, keep_frames_dir=None):
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH; install it before generating video")

    base = _static_base()
    headline_font = _font(HEADLINE_SIZE, 800)
    body_font = _font(BODY_SIZE, 500)
    tag_font = _font(TAG_SIZE, 600)
    handle_font = _font(int(SIZE[0] * 0.032), 600)

    dummy_draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    body_lines = _wrap_by_width(dummy_draw, item["body"], body_font, CONTENT_WIDTH)

    frames_dir = keep_frames_dir or tempfile.mkdtemp(prefix="gm_frames_")
    os.makedirs(frames_dir, exist_ok=True)
    try:
        for i in range(TOTAL_FRAMES):
            frame = _compose_frame(item, base, i, tag_font, headline_font, body_font, handle_font, body_lines)
            frame.save(os.path.join(frames_dir, f"frame_{i:04d}.png"))

        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(FPS),
            "-i", os.path.join(frames_dir, "frame_%04d.png"),
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-shortest",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            out_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr[-2000:]}")
    finally:
        if not keep_frames_dir:
            shutil.rmtree(frames_dir, ignore_errors=True)

    return out_path


if __name__ == "__main__":
    import json
    with open(os.path.join(HERE, "..", "content", "content.json"), encoding="utf-8") as f:
        item = json.load(f)["items"][0]
    os.makedirs("/tmp/gm_preview", exist_ok=True)
    make_reel_video(item, "/tmp/gm_preview/reel.mp4")
    print("saved /tmp/gm_preview/reel.mp4")
