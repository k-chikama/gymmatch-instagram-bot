"""
GymMatch Instagram自動投稿スクリプト。

想定実行環境: GitHub Actions（このスクリプト自身はネットワーク越しに
Instagram Graph APIを呼び出すだけで、リポジトリへのcommit/pushはワークフロー
(.github/workflows/post.yml) 側が行う）。

流れ:
  1. content/content.json と state/state.json から次に投稿する内容を選ぶ
  2. フィード用(1080x1080)・ストーリー用(1080x1920)の画像を generated/ に書き出す
     （ファイル名はユニークにして、GitHub Pagesやraw.githubusercontent.com
       のキャッシュ衝突を避ける）
  3. state/state.json のindexを進めて保存
  4. （このスクリプトはファイルを書き出すところまで。git commit & push は
      ワークフローのステップで行い、その後に --publish で本投稿を実行する
      2段構成にしている）

環境変数:
  IG_ACCESS_TOKEN : Instagramのアクセストークン（必須）
  IG_USER_ID      : InstagramのユーザーID（必須）
  RAW_BASE_URL    : 生成画像に外部からアクセスするためのベースURL
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


def step_generate():
    """画像を生成して generated/ に保存し、生成したファイル名を stdout に出す
    （ワークフロー側でファイル名をキャプチャしてcommitし、publishステップに渡す）。"""
    sys.path.insert(0, HERE)
    from generate_image import make_feed_image, make_story_image

    item, idx = pick_next_item()
    os.makedirs(GENERATED_DIR, exist_ok=True)
    uid = uuid.uuid4().hex[:10]
    feed_name = f"feed_{uid}.png"
    story_name = f"story_{uid}.png"
    make_feed_image(item, os.path.join(GENERATED_DIR, feed_name))
    make_story_image(item, os.path.join(GENERATED_DIR, story_name))

    caption = build_caption(item)

    manifest = {
        "index": idx,
        "type": item["type"],
        "feed_file": feed_name,
        "story_file": story_name,
        "caption": caption,
    }
    manifest_path = os.path.join(GENERATED_DIR, f"manifest_{uid}.json")
    save_json(manifest_path, manifest)
    # GitHub Actions の後続ステップに渡すため、ファイル名をそのまま出力する
    print(f"MANIFEST={os.path.basename(manifest_path)}")


def build_caption(item):
    base = f"{item['headline'].replace(chr(10), ' ')}\n\n{item['body']}"
    hashtags = "\n\n#GymMatch #ジム友 #トレーニング仲間 #筋トレ女子 #筋トレ初心者 #ジム活 #筋トレアプリ"
    return base + hashtags


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


def create_and_publish(image_url, ig_user_id, token, caption=None, media_type=None, max_retries=3):
    params = {"image_url": image_url, "access_token": token}
    if caption:
        params["caption"] = caption
    if media_type:
        params["media_type"] = media_type

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

    # コンテナのステータスが FINISHED になるまで待つ
    for _ in range(12):
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
        time.sleep(5)

    pub_r = requests.post(
        f"{GRAPH_BASE}/{ig_user_id}/media_publish",
        data={"creation_id": container_id, "access_token": token},
        timeout=30,
    )
    if pub_r.status_code != 200:
        raise RuntimeError(f"publish failed: {pub_r.text}")
    return pub_r.json()["id"]


def step_publish(manifest_file):
    token = os.environ["IG_ACCESS_TOKEN"]
    ig_user_id = os.environ["IG_USER_ID"]
    raw_base = os.environ["RAW_BASE_URL"].rstrip("/")

    manifest = load_json(os.path.join(GENERATED_DIR, manifest_file))
    feed_url = f"{raw_base}/generated/{manifest['feed_file']}"
    story_url = f"{raw_base}/generated/{manifest['story_file']}"

    print(f"waiting for public availability of {feed_url}")
    if not wait_for_public(feed_url):
        print("WARNING: feed image not confirmed public yet, trying anyway")

    print("publishing feed post...")
    feed_id = create_and_publish(feed_url, ig_user_id, token, caption=manifest["caption"])
    print(f"feed post published: {feed_id}")

    print("publishing story...")
    story_id = create_and_publish(story_url, ig_user_id, token, media_type="STORIES")
    print(f"story published: {story_id}")

    state = load_json(STATE_PATH)
    state["last_posted_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state["last_feed_post_id"] = feed_id
    state["last_story_post_id"] = story_id
    save_json(STATE_PATH, state)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: post_to_instagram.py generate|publish <manifest_file>")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "generate":
        step_generate()
    elif cmd == "publish":
        step_publish(sys.argv[2])
    else:
        print(f"unknown command: {cmd}")
        sys.exit(1)
