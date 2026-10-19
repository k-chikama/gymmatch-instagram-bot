"""
GymMatch X（旧Twitter）自動投稿スクリプト。

流れ:
  1. generate : コンテンツローテーションから次の1件を選び、正方形のブランド画像を生成
  2. publish  : 画像をアップロードし、本文とともにポストを作成

X API v2は従量課金制。POST /2/tweets はURLなしのテキスト投稿で約$0.015/件。

画像アップロードだけは例外的にOAuth 1.0a（Consumer Key/Secret +
Access Token/Secret）を使う。OAuth 2.0のユーザートークンには
`media.write`スコープが付与できない（console.x.comのトークン発行画面に
その選択肢が無い）ため、新しい v2 の /2/media/upload をOAuth 2.0
Bearerトークンで呼ぶと403 Forbiddenになる。昔からある
upload.twitter.com/1.1/media/upload.json をOAuth 1.0aで呼ぶのが
確実なため、画像アップロードだけこちらを使う。

ツイート本文の投稿（POST /2/tweets）自体はOAuth 2.0のアクセストークンを
使う（これは正常に動作する）。認証はOAuth 2.0（Authorization Code +
PKCE で developer console から直接発行した本人アカウント用のアクセス
トークン/リフレッシュトークン）。アクセストークンの有効期限は短い
（数時間程度）ため、このスクリプトを実行するワークフローは毎回
scripts/refresh_token_x.py で事前にリフレッシュする前提。
"""
import os
import sys
import time

import requests
from requests_oauthlib import OAuth1

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
GENERATED_DIR = os.path.join(ROOT, "generated")

sys.path.insert(0, HERE)
from post_to_instagram import pick_next_item, build_caption, load_json, save_json, STATE_PATH  # noqa: E402

API_BASE = "https://api.x.com/2"

# CJK・全角文字はX上で「幅2」として文字数カウントされるため、
# 単純な文字数ではなく重み付き長さで280以内に収める。
_WIDE_RANGES = [
    (0x1100, 0x115F), (0x2E80, 0xA4CF), (0xAC00, 0xD7A3),
    (0xF900, 0xFAFF), (0xFF00, 0xFF60), (0xFFE0, 0xFFE6),
    (0x20000, 0x3FFFD),
]


def _is_wide(ch):
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _WIDE_RANGES)


def _weighted_len(text):
    return sum(2 if _is_wide(ch) else 1 for ch in text)


def _trim_for_x(text, limit=280):
    if _weighted_len(text) <= limit:
        return text
    trimmed = ""
    for ch in text:
        candidate = trimmed + ch
        if _weighted_len(candidate) + 1 > limit:
            break
        trimmed = candidate
    return trimmed.rstrip() + "…"


def step_generate():
    sys.path.insert(0, HERE)
    from generate_image import make_feed_image

    item, idx = pick_next_item()
    os.makedirs(GENERATED_DIR, exist_ok=True)
    import uuid
    uid = uuid.uuid4().hex[:10]
    img_name = f"x_{uid}.png"
    make_feed_image(item, os.path.join(GENERATED_DIR, img_name))

    text = _trim_for_x(build_caption(item, with_hashtags=True))

    manifest = {"kind": "x", "index": idx, "type": item["type"], "image_file": img_name, "text": text}
    manifest_path = os.path.join(GENERATED_DIR, f"manifest_x_{uid}.json")
    save_json(manifest_path, manifest)
    print(f"MANIFEST={os.path.basename(manifest_path)}")


def upload_media(image_path):
    """OAuth 1.0a経由で画像をアップロードする（理由は冒頭のコメント参照）。"""
    auth = OAuth1(
        os.environ["X_CONSUMER_KEY"],
        os.environ["X_CONSUMER_SECRET"],
        os.environ["X_OAUTH1_ACCESS_TOKEN"],
        os.environ["X_OAUTH1_ACCESS_TOKEN_SECRET"],
    )
    with open(image_path, "rb") as f:
        files = {"media": (os.path.basename(image_path), f, "image/png")}
        r = requests.post(
            "https://upload.twitter.com/1.1/media/upload.json",
            auth=auth,
            files=files,
            timeout=60,
        )
    if r.status_code >= 300:
        raise RuntimeError(f"media upload failed: {r.status_code} {r.text}")
    data = r.json()
    if "media_id_string" in data:
        return data["media_id_string"]
    raise RuntimeError(f"unexpected media upload response: {data}")


def create_post(token, text, media_id):
    r = requests.post(
        f"{API_BASE}/tweets",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"text": text, "media": {"media_ids": [media_id]}},
        timeout=30,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"tweet creation failed: {r.status_code} {r.text}")
    return r.json()


def step_publish(manifest_file):
    token = os.environ["X_ACCESS_TOKEN"]
    manifest_path = os.path.join(GENERATED_DIR, manifest_file)
    manifest = load_json(manifest_path)
    image_path = os.path.join(GENERATED_DIR, manifest["image_file"])

    media_id = upload_media(image_path)
    result = create_post(token, manifest["text"], media_id)
    post_id = result.get("data", {}).get("id")

    state = load_json(STATE_PATH)
    state["last_posted_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state["last_x_post_id"] = post_id
    save_json(STATE_PATH, state)
    print(f"Published to X: id={post_id}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "generate":
        step_generate()
    elif cmd == "publish":
        if len(sys.argv) < 3:
            print("usage: post_to_x.py publish <manifest_file>")
            sys.exit(1)
        step_publish(sys.argv[2])
    else:
        print("usage: post_to_x.py generate|publish <manifest_file>")
        sys.exit(1)
