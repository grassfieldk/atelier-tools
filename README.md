# Atelier Tools

アトリエシリーズのゲームデータ抽出・閲覧ツール


## 対応タイトル

- メルルのアトリエ DX


## セットアップ

```powershell
(&mise activate pwsh) | Out-String | Invoke-Expression
mise install
mise run setup
```

## 使用方法

### ゲームデータ抽出

```powershell
mise run scan
# ゲームインストールパスが検出されない場合は次のコマンドで指定する
mise run scan -- --game-path "<インストールパス>"
```

※ データは data/ に出力される

### 抽出データの利用

```powershell
# 検索
mise run search -- "<検索文字列>" --category all --language all --limit 100
# CSV エクスポート
mise run export
```

### Web UI 起動

```powershell
mise run dev
```


## 技術スタック

- Python 3.14
- FastAPI
- Uvicorn
- SQLite
- React
- TypeScript
- Vite
- Mantine
- Node.js
- pytest
- mise
