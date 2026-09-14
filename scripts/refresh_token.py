"""
Instagramの長期アクセストークンをリフレッシュし、GitHubリポジトリの
Secret (IG_ACCESS_TOKEN) を新しい値に更新する（任意機能）。

前提:
  - IG_ACCESS_TOKEN が発行から24時間以上経過していること（Meta仕様）
  - リポジトリに GH_PAT という Secret（"repo" スコープ持ちの Personal
    Access Token）が登録されていること。これが無い場合はリフレッシュを
    スキップし、ログにその旨を出すだけで正常終了する
    （＝自動投稿本体は失敗させない）。

GH_PATを用意しない場合、Instagramの長期トークンは発行から約60日で失効する。
その場合は約50日以内を目安に、Graph API Explorerなどで新しいトークンを
発行し、GitHubのSecretを手動で更新すること。
"""
import base64
import json
import os
import sys

import requests

try:
    from nacl import encoding, public
except ImportError:
    public = None


def refresh_ig_token(current_token):
    r = requests.get(
        "https://graph.instagram.com/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": current_token},
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"refresh failed: {r.status_code} {r.text}")
    data = r.json()
    return data["access_token"], data.get("expires_in")


def update_github_secret(owner, repo, gh_pat, secret_name, secret_value):
    if public is None:
        print("PyNaCl not installed; cannot update GitHub secret automatically. "
              "Add 'PyNaCl' to requirements.txt if you want this feature.")
        return False

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
    return True


if __name__ == "__main__":
    # NOTE: this script deliberately never prints the token value itself to
    # stdout/stderr (those become GitHub Actions logs). The new token, if any,
    # is written to NEW_TOKEN_FILE so the workflow step can mask it with
    # `::add-mask::` before exporting it, keeping it out of the log stream.
    token = os.environ.get("IG_ACCESS_TOKEN")
    gh_pat = os.environ.get("GH_PAT")
    repo_full = os.environ.get("GITHUB_REPOSITORY")  # "owner/repo" (Actions provides this)
    new_token_file = os.environ.get("NEW_TOKEN_FILE", "/tmp/new_ig_token.txt")

    if not token:
        print("IG_ACCESS_TOKEN not set; skipping refresh.")
        sys.exit(0)

    if not gh_pat:
        print("GH_PAT secret not set; skipping automatic token refresh. "
              "Remember to manually refresh IG_ACCESS_TOKEN before it expires (~60 days).")
        sys.exit(0)

    try:
        new_token, expires_in = refresh_ig_token(token)
    except Exception as e:
        print(f"Token refresh failed (continuing with existing token): {e}")
        sys.exit(0)

    owner, repo = repo_full.split("/")
    ok = update_github_secret(owner, repo, gh_pat, "IG_ACCESS_TOKEN", new_token)
    if ok:
        with open(new_token_file, "w") as f:
            f.write(new_token)
        days = (expires_in or 0) / 86400
        print(f"Token refreshed and GitHub secret updated. New token valid for ~{days:.0f} days.")
