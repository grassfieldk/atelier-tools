from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from ..core import DATA_ROOT, DB_PATH, Installation, build_index, diagnose, search_structured
from ..models import DATA_KINDS, Cell, Dataset, GameDefinition, Ingredient, Item, LocalizedText, MapArea, Monster, NumberCell, NumberColumn, Recipe, Reference, TextCell, TextColumn, Trait
from .base import ExtractionContext, ExtractionResult


def label(ja: str, en: str, zh: str) -> LocalizedText:
    return LocalizedText(ja=ja, en=en, zh=zh)


class MeruruAdapter:
    definition = GameDefinition(
        id="meruru-dx",
        title=label("メルルのアトリエ DX", "Atelier Meruru DX", "梅露露的炼金工房 DX"),
        series=label("アーランドシリーズ", "Arland Series", "亚兰德系列"),
        columns={
            "items": [TextColumn(id="name", label=label("名称", "Name", "名称")), TextColumn(id="categories", label=label("カテゴリ", "Categories", "类别")), NumberColumn(id="level", label=label("レベル", "Level", "等级")), NumberColumn(id="value", label=label("価格", "Price", "价格"))],
            "recipes": [TextColumn(id="name", label=label("名称", "Name", "名称")), TextColumn(id="ingredients", label=label("材料", "Ingredients", "材料")), NumberColumn(id="level", label=label("レベル", "Level", "等级")), NumberColumn(id="days", label=label("日数", "Days", "天数"))],
            "traits": [TextColumn(id="name", label=label("名称", "Name", "名称")), NumberColumn(id="cost", label=label("コスト", "Cost", "成本")), TextColumn(id="description", label=label("説明", "Description", "说明"))],
            "maps": [TextColumn(id="name", label=label("名称", "Name", "名称")), TextColumn(id="items", label=label("採取アイテム", "Gathering items", "采集道具")), TextColumn(id="monsters", label=label("敵", "Enemies", "敌人")), TextColumn(id="description", label=label("説明", "Description", "说明"))],
            "monsters": [TextColumn(id="name", label=label("名称", "Name", "名称")), NumberColumn(id="level", label=label("レベル", "Level", "等级"))],
        },
    )

    def diagnose(self, game_path: str | Path | None = None) -> Installation:
        return diagnose(game_path)

    def extract(self, game_path: str | Path | None, context: ExtractionContext) -> ExtractionResult:
        if not context.analysis.exists() and (DATA_ROOT / "analysis").is_dir():
            shutil.copytree(DATA_ROOT / "analysis", context.analysis)
        source = context.directory / "extracted.sqlite3"
        build_index(game_path, database=source, summary_path=context.directory / "extracted-summary.json", analysis_root=context.analysis)
        return ExtractionResult(self.from_database(source), source)

    def from_database(self, database: Path = DB_PATH) -> Dataset:
        with closing(sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            raw = {kind: [dict(row) for row in connection.execute(f"SELECT * FROM {kind}")] for kind in DATA_KINDS}
            categories = {row["category_id"]: label(row["name_ja"], row["name_en"], row["name_zh"]) for row in connection.execute("SELECT * FROM categories")}
            category_ids: dict[int, list[int]] = {}
            for row in connection.execute("SELECT * FROM item_categories ORDER BY slot"):
                category_ids.setdefault(row["item_id"], []).append(row["category_id"])
            localized = {language: {kind: {row["id"]: row for row in search_structured(kind, language=language, database=database)} for kind in DATA_KINDS} for language in ("ja", "en", "zh")}
        entities: dict[str, list[dict]] = {}
        for kind in DATA_KINDS:
            entities[kind] = []
            for record in raw[kind]:
                identifier = record[{"items": "game_item_id", "recipes": "recipe_id", "traits": "trait_id", "maps": "map_id", "monsters": "monster_id"}[kind]]
                names = {language: localized[language][kind][identifier]["name"] for language in ("ja", "en", "zh")}
                cells: dict[str, dict[str, Cell]] = {}
                for column in self.definition.columns.for_kind(kind):
                    values = {}
                    for language in ("ja", "en", "zh"):
                        row = localized[language][kind][identifier]
                        value = row.get(column.id)
                        separator = ", " if language == "en" else "、"
                        if kind == "recipes" and column.id == "ingredients":
                            value = separator.join(f"{ingredient['name'] or '#' + str(ingredient['reference_id'])} {ingredient['quantity']}" for ingredient in row["ingredients"])
                        elif kind == "maps" and column.id in {"items", "monsters"}:
                            value = separator.join(reference["name"] for reference in row[column.id])
                        elif kind == "maps" and column.id == "name" and row["alternate_name"] and row["alternate_name"] != value:
                            value = f"{value} / {row['alternate_name']}"
                        elif kind == "maps" and column.id == "description":
                            value = value or row["alternate_description"]
                        values[language] = NumberCell(type="number", value=value) if column.type == "number" else TextCell(type="text", value=value)
                    cells[column.id] = values
                entity = {"kind": kind, "id": identifier, "name": names, "cells": cells, "attributes": record}
                if kind == "items":
                    entity["categories"] = category_ids.get(identifier, [])
                elif kind == "recipes":
                    entity["result"] = record["item_id"]
                    entity["ingredients"] = [Ingredient(reference=Reference(kind="categories" if ingredient["reference_type"] == "category" else "items", id=ingredient["reference_id"]), quantity=ingredient["quantity"]) for ingredient in localized["ja"][kind][identifier]["ingredients"]]
                elif kind == "maps":
                    entity["items"] = [value["id"] for value in localized["ja"][kind][identifier]["items"]]
                    entity["monsters"] = [value["id"] for value in localized["ja"][kind][identifier]["monsters"]]
                entities[kind].append(entity)
        return Dataset(items=[Item.model_validate(value) for value in entities["items"]], recipes=[Recipe.model_validate(value) for value in entities["recipes"]], traits=[Trait.model_validate(value) for value in entities["traits"]], maps=[MapArea.model_validate(value) for value in entities["maps"]], monsters=[Monster.model_validate(value) for value in entities["monsters"]], categories=categories)
