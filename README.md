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
mise run scan -- --game meruru-dx
# ゲームインストールパスが検出されない場合は次のコマンドで指定する
mise run scan -- --game-path "<インストールパス>"
```

データは `data/{game_id}/` に出力される。作品を省略した場合は `meruru-dx` が対象となる

### 既存データの移行

旧形式のメルルのデータは再抽出せずに移行できる。元の DB と解析ファイルは保持され、移行先にデータがある場合は上書きしない

```powershell
mise run migrate -- --game meruru-dx
```

### 抽出データの利用

```powershell
# 検索
mise run search -- "<検索文字列>" --category all --language all --limit 100
# CSV エクスポート
mise run export
```

CSV は `data/{game_id}/export/` に出力される。5 分類の CSV に加え、抽出元の補助テーブルは `source-*.csv` に出力される

### Web UI 起動

```powershell
mise run dev
```

## 共通データ契約

全作品はアイテム・レシピ・特性・探索地・敵の 5 分類を持つ。データがない分類は空配列、取得できない値は `null` として扱う。各分類には ID と多言語名称があり、レシピの完成アイテム・材料、探索地の採取アイテム・敵は ID で関連付ける

`atelier_tools/models.py` がデータ契約の定義元となる。Pydantic による抽出結果の検証と API の応答検証に加え、同じ JSON Schema から TypeScript 型を生成し、ブラウザでは Ajv で受信データを検証する。生成ファイルは手で編集しない

```powershell
# モデルを変更した後に型とスキーマを更新する
mise run contract
# 型チェックと配置用ビルド
mise run frontend-build
```

文字列セルと数値セル、5 分類のデータは判別子を持つ。作品ごとの列定義とセルのキー・値型・言語が一致することを保存時に検証し、列とセルの対応はブラウザでも検証する

## 作品の追加

`atelier_tools/games/base.py` の `GameAdapter` に沿ったアダプターを `atelier_tools/games/` に追加し、`registry.py` に登録する。アダプターは作品定義、インストール検出、抽出処理を実装する

作品定義ではタイトル・シリーズ名と 5 分類の列を設定する。列は文字列列と数値列を区別し、抽出結果のセルに同じ ID と値型を設定する。日数・コスト・能力値などの項目は作品ごとに設定でき、共通テーブルの変更は必要ない。レシピ・探索地の関連情報はセルの表示文字列とは別に型付きの参照として保持する

抽出処理には作品別の保存先と解析ファイルのディレクトリが `ExtractionContext` で渡される。処理結果は `Dataset` を返し、共通コントローラーが検証・保存・API 表示・CSV 出力を行う。元の解析値は追加属性として保持できる

メルルのアダプターは `games/meruru.py`、旧形式の DB とインストール検出は `games/meruru_backend.py`、バイナリの解析は `meruru.py` に分かれている。`core.py` にある旧公開関数は互換用の入口として残している

作品別の構造は以下のとおり

```text
data/{game_id}/
	data.sqlite3
	summary.json
	analysis/
	export/
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
- TanStack Table
- Pydantic
- Ajv
- json-schema-to-typescript
- Node.js
- pytest
- mise
