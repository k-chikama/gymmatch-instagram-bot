"""
GymMatch Instagram自動投稿スクリプト。

想定実行環境: GitHub Actions（このスクリプト自身はネットワーク越しに
Instagram Graph APIを呼び出すだけで、リポジトリへのcommit/pushはワークフロー
側が行う）。フィード・ストーリー・リールはそれぞれ独立したワークフロー
(.github/workflows/post_feed.yml, post_story.yml, post_reel.yml) から
このスクリプトを呼び出す想定。

サブコマンド:
  generate-feed   : フィード用画像を生成 (1080x1080)
  generate-story  : ストーリー用画像を生成 (1080x1920)
  generate-reel   : リール用動画を生成 (1080x1920, 約7秒)
  publish <manifest_file> : generate-* が書き出したmanifestを元に投稿する

いずれも「content/content.json の次のアイテムを1つ消費して使う」という
共通のローテーションを使うので、フィード・ストーリー・リールがそれぞれ
実行されるたびに順番が1つずつ進む。

環境変数:
  IG_ACCESS_TOKEN : Instagramのアクセストークン（必須）
  IG_USER_ID      : InstagramのユーザーID（必須）
  RAW_BASE_URL    : 生成ファイルに外部からアクセスするためのベースURL
                    例: https://raw.githubusercontent.com/<owner>/<repo>/<branch>
                    （必須。publishステップでのみ使用）
"""
import json
import os
import sys
import time
import uuid
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
CONTENT_PATH = os.path.join(ROOT, "content", "content.json")
STATE_PATH = os.path.join(ROOT, "state", "state.json")
GENERATED_DIR = os.path.join(ROOT, "generated")

GRAPH_BASE = "https://graph.instagram.com/v21.0"


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def pick_next_item():
    content = load_json(CONTENT_PATH)
    state = load_json(STATE_PATH)
    items = content["items"]
    idx = state.get("next_index", 0) % len(items)
    item = items[idx]
    state["next_index"] = (idx + 1) % len(items)
    save_json(STATE_PATH, state)
    return item, idx


def build_caption(item, with_hashtags=True):
    base = f"{item['headline'].replace(chr(10), ' ')}\n\n{item['body']}"
    if not with_hashtags:
        return base
    hashtags = "\n\n#GymMatch #ジム友 #トレーニング仲間 #筋トレ女子 #筋トレ初心者 #ジム活 #筋トレアプリ"
    return base + hashtags


def _write_manifest(kind, idx, item, **fields):
    os.makedirs(GENERATED_DIR, exist_ok=True)
    uid = uuid.uuid4().hex[:10]
    manifest = {"kind": kind, "index": idx, "type": item["type"], **fields}
    manifest_path = os.path.join(GENERATED_DIR, f"manifest_{kind}_{uid}.json")
    save_json(manifest_path, manifest)
    print(f"MANIFEST={os.path.basename(manifest_path)}")
    return manifest_path


def step_generate_feed():
    sys.path.insert(0, HERE)
    from generate_image import make_feed_image

    item, idx = pick_next_item()
    os.makedirs(GENERATED_DIR, exist_ok=True)
    uid = uuid.uuid4().hex[:10]
    feed_name = f"feed_{uid}.png"
    make_feed_image(item, os.path.join(GENERATED_DIR, feed_name))
    _write_manifest("feed", idx, item, feed_file=feed_name, caption=build_caption(item))


def step_generate_story():
    sys.path.insert(0, HERE)
    from generate_image import make_story_image

    item, idx = pick_next_item()
    os.makedirs(GENERATED_DIR, exist_ok=True)
    uid = uuid.uuid4().hex[:10]
    story_name = f"story_{uid}.png"
    make_story_image(item, os.path.join(GENERATED_DIR, story_name))
    _write_manifest("story", idx, item, story_file=story_name)


def step_generate_reel():
    sys.path.insert(0, HERE)
    from generate_video import make_reel_video

    item, idx = pick_next_item()
    os.makedirs(GENERATED_DIR, exist_ok=True)
    uid = uuid.uuid4().hex[:10]
    reel_name = f"reel_{uid}.mp4"
    make_reel_video(item, os.path.join(GENERATED_DIR, reel_name))
    _write_manifest("reel", idx, item, reel_file=reel_name, caption=build_caption(item))


def wait_for_public(url, attempts=8, delay=5):
    for i in range(attempts):
        try:
            r = requests.head(url, timeout=10, allow_redirects=True)
            if r.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(delay)
    return False


def create_and_publish(ig_user_id, token, media_url, media_kind, caption=None, max_retries=3,
                        status_attempts=12, status_delay=5):
    """media_kind: 'image' (feed) | 'story' | 'reel'"""
    params = {"access_token": token}
    if media_kind == "reel":
        params["media_type"] = "REELS"
        params["video_url"] = media_url
    elif media_kind == "story":
        params["media_type"] = "STORIES"
        params["image_url"] = media_url
    else:
        params["image_url"] = media_url
    if caption:
        params["caption"] = caption

    last_err = None
    for attempt in range(max_retries):
        r = requests.post(f"{GRAPH_BASE}/{ig_user_id}/media", data=params, timeout=30)
        if r.status_code == 200:
            container_id = r.json()["id"]
            break
        last_err = r.text
        time.sleep(5)
    else:
        raise RuntimeError(f"container creation failed after retries: {last_err}")

    # コンテナのステータスが FINISHED になるまで待つ（動画は処理に時間がかかる）
    for _ in range(status_attempts):
        status_r = requests.get(
            f"{GRAPH_BASE}/{container_id}",
            params={"fields": "status_code", "access_token": token},
            timeout=15,
        )
        status = status_r.json().get("status_code")
        if status == "FINISHED":
            break
        if status == "ERROR":
            raise RuntimeError(f"container {container_id} errored: {status_r.text}")
        time.sleep(status_delay)
    else:
        raise RuntimeError(f"container {container_id} did not finish processing in time")

    pub_r = requests.post(
        f"{GRAPH_BASE}/{ig_user_id}/media_publish",
        data={"creation_id": container_id, "access_token": token},
        timeout=30,
    )
    if pub_r.status_code != 200:
        raise RuntimeError(f"publish failed: {pub_r.text}")
    return pub_r.json()["id"]


def _update_state(**fields):
    state = load_json(STATE_PATH)
    state["last_posted_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state.update(fields)
    save_json(STATE_PATH, state)


def step_publish(manifest_file):
    token = os.environ["IG_ACCESS_TOKEN"]
    ig_user_id = os.environ["IG_USER_ID"]
    raw_base = os.environ["RAW_BASE_URL"].rstrip("/")

    manifest = load_json(os.path.join(GENERATED_DIR, manifest_file))
    kind = manifest["kind"]

    if kind == "feed":
        url = f"{raw_base}/generated/{manifest['feed_file']}"
        print(f"waiting for public availability of {url}")
        if not wait_for_public(url):
            print("WARNING: feed image not confirmed public yet, trying anyway")
        post_id = create_and_publish(ig_user_id, token, url, "image", caption=manifest.get("caption"))
        print(f"feed post published: {post_id}")
        _update_state(last_feed_post_id=post_id)

    elif kind == "story":
        url = f"{raw_base}/generated/{manifest['story_file']}"
        print(f"waiting for public availability of {url}")
        if not wait_for_public(url):
            print("WARNING: story image not confirmed public yet, trying anyway")
        post_id = create_and_publish(ig_user_id, token, url, "story")
        print(f"story published: {post_id}")
        _update_state(last_story_post_id=post_id)

    elif kind == "reel":
        url = f"{raw_base}/generated/{manifest['reel_file']}"
        print(f"waiting for public availability of {url}")
        if not wait_for_public(url, attempts=12, delay=5):
            print("WARNING: reel video not confirmed public yet, trying anyway")
        # 動画はコンテナ処理に時間がかかるため、長めにポーリングする
        post_id = create_and_publish(
            ig_user_id, token, url, "reel", caption=manifest.get("caption"),
            status_attempts=36, status_delay=10,
        )
        print(f"reel published: {post_id}")
        _update_state(last_reel_post_id=post_id)

    else:
        raise ValueError(f"unknown manifest kind: {kind}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: post_to_instagram.py generate-feed|generate-story|generate-reel|publish <manifest_file>")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "generate-feed":
        step_generate_feed()
    elif cmd == "generate-story":
        step_generate_story()
    elif cmd == "generate-reel":
        step_generate_reel()
    elif cmd == "publish":
        step_publish(sys.argv[2])
    else:
        print(f"unknown command: {cmd}")
        sys.exit(1)
