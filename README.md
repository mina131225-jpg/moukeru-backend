# Proof of Human - Backend (Render Deploy)

## Render へのデプロイ手順

### 前提条件
- GitHub アカウント
- Render アカウント (https://render.com)
- PostgreSQL データベース（Render上で作成済み）

---

### Step 1: GitHub リポジトリの作成

1. GitHub (https://github.com) にログイン
2. 右上の「+」→「New repository」をクリック
3. リポジトリ名: `proof-of-human-backend`
4. Private（非公開）を選択
5. 「Create repository」をクリック

### Step 2: コードをGitHubにアップロード

**方法A: Git コマンドライン（推奨）**

```bash
# 1. ZIPを解凍したフォルダに移動
cd proof-of-human-backend

# 2. Gitリポジトリを初期化
git init

# 3. .gitignore を作成
echo "__pycache__/
*.pyc
.env
logs/
*.log
.venv/
venv/" > .gitignore

# 4. すべてのファイルをステージング
git add .

# 5. 最初のコミット
git commit -m "Initial commit: Proof of Human backend"

# 6. メインブランチに変更
git branch -M main

# 7. リモートリポジトリを追加（URLはGitHubで作成したリポジトリのもの）
git remote add origin https://github.com/YOUR_USERNAME/proof-of-human-backend.git

# 8. プッシュ
git push -u origin main
```

**方法B: GitHub Web UI**

1. 作成したリポジトリページを開く
2. 「uploading an existing file」リンクをクリック
3. ZIPを解凍したフォルダ内のすべてのファイルをドラッグ＆ドロップ
4. 「Commit changes」をクリック

### Step 3: Render でWeb Serviceを作成

1. Render (https://dashboard.render.com) にログイン
2. 「New +」→「Web Service」をクリック
3. 「Build and deploy from a Git repository」を選択
4. GitHubアカウントを接続し、`proof-of-human-backend` リポジトリを選択
5. 以下の設定を入力:

| 設定項目 | 値 |
|---------|-----|
| **Name** | `proof-of-human-backend` |
| **Region** | Oregon (US West) ※お好みで |
| **Branch** | `main` |
| **Runtime** | `Python` |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| **Plan** | Free（または有料プラン） |

### Step 4: 環境変数の設定

Render Dashboard → 作成したサービス → 「Environment」タブで以下を設定:

| 変数名 | 値 | 説明 |
|--------|-----|------|
| `DATABASE_URL` | `postgresql://...` | Render PostgreSQLの接続URL |
| `ENVIRONMENT` | `prod` | 本番環境 |
| `RESEND_API_KEY` | `re_...` | メール送信用 |
| `STRIPE_SECRET_KEY` | `sk_live_...` | Stripe決済用 |
| `STRIPE_WEBHOOK_SECRET` | `whsec_...` | Stripeウェブフック用 |
| `JWT_SECRET_KEY` | (ランダム文字列) | JWT認証用 |
| `FRONTEND_URL` | `https://proof-of-human.io` | フロントエンドURL |

### Step 5: デプロイ確認

1. 環境変数を保存すると自動的にデプロイが開始されます
2. ログを確認して正常に起動していることを確認
3. `https://your-service.onrender.com/health` にアクセスして `{"status": "healthy"}` が返ることを確認
4. `https://your-service.onrender.com/docs` でAPI仕様書を確認

### Step 6: フロントエンドの接続設定

フロントエンドの環境変数 `VITE_API_BASE_URL` を Render のバックエンドURLに設定:

```
VITE_API_BASE_URL=https://your-service.onrender.com
```

---

## ファイル構成

```
├── Procfile              # Render起動コマンド
├── render.yaml           # Render Blueprint設定
├── runtime.txt           # Pythonバージョン指定
├── requirements.txt      # Python依存パッケージ
├── .env.example          # 環境変数テンプレート
├── main.py               # FastAPIアプリケーション本体
├── lambda_handler.py     # AWS Lambda用（Renderでは不使用）
├── alembic.ini           # DBマイグレーション設定
├── alembic/              # DBマイグレーションファイル
├── core/                 # コア設定（config, database, auth）
├── models/               # データベースモデル
├── routers/              # APIエンドポイント
├── services/             # ビジネスロジック
├── schemas/              # リクエスト/レスポンススキーマ
├── dependencies/         # FastAPI依存性注入
├── middlewares/           # ミドルウェア
└── utils/                # ユーティリティ
```

## トラブルシューティング

### デプロイが失敗する場合
- Renderのログを確認してエラーメッセージを確認
- `requirements.txt` の依存関係が正しいか確認
- Pythonバージョンが `runtime.txt` と一致しているか確認

### データベース接続エラー
- `DATABASE_URL` が正しい形式か確認: `postgresql://user:pass@host:port/dbname`
- Render PostgreSQLの「Internal Database URL」を使用（同じRender内の場合）
- 外部DBの場合は「External Database URL」を使用

### ヘルスチェックが失敗する場合
- `/health` エンドポイントが正常に動作しているか確認
- ポートが `$PORT` 環境変数を使用しているか確認