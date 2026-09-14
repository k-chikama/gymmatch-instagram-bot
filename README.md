# GymMatch Instagram 自動投稿bot

GitHub Actions上で動く、GymMatch公式Instagram（@gymmatchapp）向けの自動投稿システムです。
Claudeのクラウド環境やご自身のPCの起動状態に依存せず、GitHub側のスケジュールで
**週2回（水・土 19:00頃）に自動でフィード投稿＋ストーリー投稿**を行います。

## できること

- ブランド画像（オレンジ系、GymMatchのロゴ入り）を自動生成してフィード投稿
- 同じ内容をストーリー用の縦長画像でも自動投稿
- 「使い方Tips / モチベーション / お知らせ」の3種類のコンテンツをローテーション
  （`content/content.json` に18件収録。自由に追加・編集可能）
- Instagramの長期アクセストークンの自動更新（任意設定、後述）

## セットアップ手順

### 1. GitHubリポジトリを作る

1. https://github.com にアクセスし、アカウントがなければ無料登録
2. 右上の「+」→「New repository」
3. リポジトリ名は任意（例: `gymmatch-instagram-bot`）
4. **Public（公開）** を選択してください（理由: 生成した画像をInstagram側が
   取得できるURLとして `raw.githubusercontent.com` を使うため。Privateだと
   Instagram側から画像を取得できません。画像は宣伝用の投稿画像だけなので、
   公開されても問題ない内容です。アクセストークン等の秘密情報は次のSecrets機能で
   別管理するので、リポジトリ自体に秘密情報は一切含まれません）
5. 「Create repository」

### 2. このフォルダの中身をアップロード

一番簡単なのはブラウザからのドラッグ&ドロップです。

1. 作成したリポジトリのページで「uploading an existing file」をクリック
2. このZIPを展開してできた中身（`.github` フォルダ含む全部）をまとめてドラッグ&ドロップ
   - ブラウザのアップロードでは `.github` のような隠しフォルダ的なものが
     反映されないことがあります。うまくいかない場合は、GitHub Desktop
     （無料アプリ）を使うか、以下のコマンドをお使いのMacのターミナルで
     実行してください（フォルダをDesktopに展開したと仮定）:
     ```
     cd ~/Desktop/gymmatch-instagram-bot
     git init
     git add .
     git commit -m "initial commit"
     git branch -M main
     git remote add origin https://github.com/【あなたのユーザー名】/【リポジトリ名】.git
     git push -u origin main
     ```
3. コミットメッセージは適当でよいので「Commit changes」

### 3. Secrets（秘密情報）を登録する

リポジトリの **Settings → Secrets and variables → Actions → New repository secret**
から、以下を1つずつ登録してください。

| Name | Value |
|---|---|
| `IG_ACCESS_TOKEN` | 今回取得済みのInstagramアクセストークン |
| `IG_USER_ID` | `27553152227691269` |

`GH_PAT` は任意です（後述の「トークン自動更新」を使う場合のみ）。

**注意**: このアクセストークンは以前このチャットで共有いただいたものです。
チャット履歴以外の場所（他人に見せるドキュメント等）には貼らないようご注意ください。
GitHubのSecretsは暗号化されて保存され、ログにも表示されない安全な保管場所です。

### 4. 手動実行してテストする

1. リポジトリの「Actions」タブを開く
2. 左側の「GymMatch Instagram Auto Post」を選択
3. 右側の「Run workflow」ボタン→「Run workflow」で今すぐ1回実行
4. 実行中の行をクリックすると進行状況とログが見られます
5. 数分待って、Instagram（@gymmatchapp）に投稿とストーリーが出れば成功です

初回はここでうまくいかないことがあっても心配いりません。ログにエラーメッセージが
出るので、それを見ながら一緒に直しましょう。

### 5. あとは自動運転

毎週水曜・土曜19:00頃（日本時間）に自動で実行されます。パソコンやスマホの
電源、Claudeアプリの起動状況に一切関係なく動きます。

## コンテンツを追加・編集する

`content/content.json` を編集するだけです。`headline`（見出し、`\n`で改行）、
`body`（本文）、`tag`（バッジに出る短いラベル）、`type`（tip / motivation / update）
を1件ずつ追加してください。リストの先頭から順番に使われ、最後まで行くとまた
先頭に戻ります。

## トークン自動更新について（任意・上級者向け）

Instagramの長期アクセストークンは発行から約60日で失効します。何もしないと
60日後くらいから投稿が失敗するようになるので、どちらかの対応が必要です。

- **手動更新（シンプル）**: 50日おきくらいを目安に、Graph API Explorerで
  新しいトークンを発行し、`IG_ACCESS_TOKEN` のSecretを上書きする
- **自動更新（このリポジトリに組み込み済み、有効化は任意）**: 実行のたびに
  トークンを自動延長し、Secretも自動で書き換えます。有効化するには、
  GitHubの「repo」スコープを持つPersonal Access Token（Settings → Developer
  settings → Personal access tokens で発行）を作成し、`GH_PAT` という名前で
  Secretに登録するだけです。登録しなければこの機能は自動でスキップされ、
  通常の投稿には影響しません。

## トラブルシューティング

- Actionsのログで `container creation failed` と出た場合: アクセストークンが
  失効している可能性が高いです。新しいトークンを取得してSecretを更新してください。
- 画像が反映されない/真っ黒などの場合: `generated/` フォルダに実際にPNGが
  コミットされているか、リポジトリがPublicになっているか確認してください。
