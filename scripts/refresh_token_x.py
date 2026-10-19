"""
XのOAuth 2.0アクセストークンをリフレッシュし、GitHub Secrets
(X_ACCESS_TOKEN, X_REFRESH_TOKEN) を新しい値に更新する。

Instagramと違い、Xのユーザーアクセストークンは有効期限が短い
（数時間程度）ため、このスクリプトは投稿ワークフローの実行のたびに
必ず呼び出す（任意機能ではない）。

さらにXのリフレッシュトークンは「ローテーション方式」（1回使うと
新しい値に置き換わり、古い値は二度と使えなくなる）ため、リフレッシュで
得た新しい refresh_token を毎回必ずSecretへ書き戻す必要がある。
これを怠ると次回の実行でリフレッシュ自体が失敗し、投稿が止まる。

前提: リポジトリに GH_PAT という Secret（"repo" スコープ持ちの
Personal Access Token）が登録されていること。
"""
import base64
import os
import sys

import requests

try:
    from nacl import encoding, public
except ImportError:
    public = None

TOKEN_URL = "https://api.x.com/2/oauth2/token"


def refresh_x_token(client_id, client_secret, refresh_token):
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    r = requests.post(
        TOKEN_URL,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        },
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"X token refresh failed: {r.status_code} {r.text}")
    data = r.json()
    return data["access_token"], data.get("refresh_token"), data.get("expires_in")


def update_github_secret(owner, repo, gh_pat, secret_name, secret_value):
    if public is None:
        raise RuntimeError("PyNaCl not installed; cannot update GitHub secret automatically.")

    headers = {
        "Authorization": f"Bearer {gh_pat}",
        "Accept": "application/vnd.github+json",
    }
    key_r = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}/actions/secrets/public-key",
        headers=headers, timeout=15,
    )
    key_r.raise_for_status()
    key_data = key_r.json()

    public_key = public.PublicKey(key_data["key"].encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    encrypted_b64 = base64.b64encode(encrypted).decode("utf-8")

    put_r = requests.put(
        f"https://api.github.com/repos/{owner}/{repo}/actions/secrets/{secret_name}",
        headers=headers,
        json={"encrypted_value": encrypted_b64, "key_id": key_data["key_id"]},
        timeout=15,
    )
    put_r.raise_for_status()


if __name__ == "__main__":
    # NOTE: 値そのものをstdout/stderrに出力しない（Actionsログに残るため）。
    # 新しいトークンは一時ファイルに書き出し、ワークフロー側で
    # `::add-mask::` によるマスク処理をしてから環境変数として使う。
    client_id = os.environ.get("X_CLIENT_ID")
    client_secret = os.environ.get("X_CLIENT_SECRET")
    refresh_token = os.environ.get("X_REFRESH_TOKEN")
    gh_pat = os.environ.get("GH_PAT")
    repo_full = os.environ.get("GITHUB_REPOSITORY")
    new_access_file = os.environ.get("NEW_X_ACCESS_TOKEN_FILE", "/tmp/new_x_access_token.txt")
    new_refresh_file = os.environ.get("NEW_X_REFRESH_TOKEN_FILE", "/tmp/new_x_refresh_token.txt")

    if not (client_id and client_secret and refresh_token):
        print("X_CLIENT_ID / X_CLIENT_SECRET / X_REFRESH_TOKEN が未設定です。リフレッシュできません。")
        sys.exit(1)

    if not gh_pat:
        print("GH_PAT Secretが未設定です。Xのアクセストークンは寿命が短いため、"
              "GH_PATが無いと自動投稿を継続できません。")
        sys.exit(1)

    try:
        new_access_token, new_refresh_token, expires_in = refresh_x_token(
            client_id, client_secret, refresh_token
        )
    except Exception as e:
        print(f"トークンのリフレッシュに失敗しました: {e}")
        sys.exit(1)

    owner, repo = repo_full.split("/")
    update_github_secret(owner, repo, gh_pat, "X_ACCESS_TOKEN", new_access_token)
    if new_refresh_token:
        update_github_secret(owner, repo, gh_pat, "X_REFRESH_TOKEN", new_refresh_token)

    with open(new_access_file, "w") as f:
        f.write(new_access_token)
    if new_refresh_token:
        with open(new_refresh_file, "w") as f:
            f.write(new_refresh_token)

    mins = (expires_in or 0) / 60
    print(f"Xトークンをリフレッシュし、GitHub Secretsを更新しました（新しいアクセストークンは約{mins:.0f}分間有効）。")
