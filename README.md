# Atelier Tools

アトリエシリーズのゲームデータを、インストール済みのゲームから抽出して閲覧する個人用ツール。アイテム、レシピ、特性、探索地、敵の情報をブラウザーで検索・絞り込み・並べ替えできる。抽出したデータは CSV に出力できる


## 対応タイトル

- メルルのアトリエ DX


## 必要な環境

- Windows
- 対応タイトルのインストール済みゲーム
- 開発ツールのバージョンと実行コマンドを管理する mise

Python と Node.js は [mise.toml](mise.toml) で指定したバージョンを使用する


## セットアップ

プロジェクトのディレクトリで PowerShell を開き、以下を実行する

```powershell
(&mise activate pwsh) | Out-String | Invoke-Expression
mise install
mise run setup
```


## 使い方

初回はゲームデータを抽出してから閲覧画面を起動する

```powershell
# ゲームデータを抽出
mise run scan
# 閲覧画面を起動
mise run start
```

ゲームのインストール先は自動検出される。検出できない場合はパスを指定する

```powershell
mise run scan -- --game-path "<ゲームのインストールパス>"
```

抽出データは `data/{game_id}/` に保存される。作品は `--game` で指定でき、省略時は `meruru-dx` が対象となる

### CSV 出力とコマンド検索

```powershell
# 抽出データを CSV に出力
mise run export
# 抽出したテキストを検索
mise run search -- "<検索文字列>"
```

CSV の出力先は `data/{game_id}/export/` となる


## 開発

バックエンドは Python と FastAPI、フロントエンドは React と TypeScript を使用する

```powershell
# 開発用 API とフロントエンドを起動
mise run dev
# ソースコードを整形
mise run format
# コードと書式を検査
mise run lint
mise run format-check
# 安全な範囲で指摘を自動修正
mise run lint-fix
# フロントエンドをビルド
mise run frontend-build
# データモデルの変更後に型とスキーマを再生成
mise run contract
```

開発方針は [AGENTS.md](AGENTS.md) を参照する
