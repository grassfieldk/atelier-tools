from __future__ import annotations

import csv
import sqlite3
from contextlib import closing
from pathlib import Path

from .core import search_index
from .games.base import ExtractionContext
from .games.registry import get_game, registered_games
from .models import (
    DATA_KINDS,
    DataKind,
    DataResponse,
    Dataset,
    DetailLink,
    DetailRelation,
    DisplayCategory,
    DetailResponse,
    DisplayNumberColumn,
    DisplayReference,
    DisplayRow,
    DisplayTextColumn,
    Entity,
    GamesResponse,
    GameSummary,
    Item,
    Language,
    MapArea,
    Monster,
    Recipe,
    RecipeTree,
    RecipeTreeEdge,
    RecipeTreeNode,
)
from .storage import database_path, game_directory, load_dataset, save_dataset


def migrate_game(game_id: str) -> dict:
    import shutil

    from .core import DATA_ROOT, DB_PATH
    from .games.meruru import MeruruAdapter

    adapter = get_game(game_id)
    if not isinstance(adapter, MeruruAdapter):
        raise ValueError("この作品に旧形式のデータはありません。")
    if database_path(game_id).exists():
        raise ValueError("移行先にデータが存在します。")
    dataset = adapter.from_database(DB_PATH)
    summary = save_dataset(adapter.definition, dataset, DB_PATH)
    analysis = DATA_ROOT / "analysis"
    destination = game_directory(game_id) / "analysis"
    if analysis.is_dir() and not destination.exists():
        shutil.copytree(analysis, destination)
    return summary


def list_games(language: Language) -> GamesResponse:
    return GamesResponse(
        items=[
            GameSummary(
                id=adapter.definition.id,
                title=getattr(adapter.definition.title, language),
                series=getattr(adapter.definition.series, language),
            )
            for adapter in registered_games()
            if database_path(adapter.definition.id).is_file()
        ]
    )


def extract_game(game_id: str, game_path: str | Path | None = None) -> dict:
    adapter = get_game(game_id)
    directory = game_directory(game_id)
    context = ExtractionContext(directory=directory, analysis=directory / "analysis")
    directory.mkdir(parents=True, exist_ok=True)
    diagnosis = adapter.diagnose(game_path)
    if not diagnosis.is_valid:
        raise ValueError(" ".join(diagnosis.issues))
    result = adapter.extract(game_path, context)
    return save_dataset(adapter.definition, result.dataset, result.source_database)


def display_row(dataset: Dataset, entity: Entity, language: Language) -> DisplayRow:
    references: dict[str, list[DisplayReference]] = {}

    def reference(
        kind: DataKind, identifier: int, quantity: float | None = None
    ) -> DisplayReference:
        target = next((value for value in getattr(dataset, kind) if value.id == identifier), None)
        return DisplayReference(
            kind=kind if target is not None else None,
            id=identifier,
            name=getattr(target.name, language) if target is not None else f"#{identifier}",
            quantity=quantity,
        )

    if isinstance(entity, Recipe):
        references["name"] = [reference("items", entity.result)]
        references["ingredients"] = [
            DisplayReference(
                kind="categories",
                id=ingredient.reference.id,
                name=getattr(dataset.categories[ingredient.reference.id], language),
                quantity=ingredient.quantity,
            )
            if ingredient.reference.kind == "categories"
            else reference(ingredient.reference.kind, ingredient.reference.id, ingredient.quantity)
            for ingredient in entity.ingredients
        ]
    if isinstance(entity, MapArea):
        references["items"] = [reference("items", identifier) for identifier in entity.items]
        references["monsters"] = [
            reference("monsters", identifier) for identifier in entity.monsters
        ]
    if isinstance(entity, Monster):
        references["drops"] = [
            reference("items", drop.item if drop.item is not None else drop.source_item_id)
            for drop in entity.drops
        ]
        references["maps"] = [
            reference("maps", area.id) for area in dataset.maps if entity.id in area.monsters
        ]
    if isinstance(entity, Item):
        references["categories"] = [
            DisplayReference(
                kind="categories",
                id=identifier,
                name=getattr(dataset.categories[identifier], language),
            )
            for identifier in entity.categories
        ]
    return DisplayRow(
        id=entity.id,
        cells={key: values[language] for key, values in entity.cells.items()},
        references=references,
    )


def get_data(game_id: str, kind: DataKind, language: Language, query: str = "") -> DataResponse:
    get_game(game_id)
    definition, dataset = load_dataset(game_id)
    rows = [display_row(dataset, entity, language) for entity in getattr(dataset, kind)]
    if query:
        normalized = query.casefold()
        rows = [
            row
            for row in rows
            if any(normalized in str(cell.value or "").casefold() for cell in row.cells.values())
        ]
    return DataResponse(
        kind=kind,
        count=len(rows),
        columns=[
            DisplayNumberColumn(id=column.id, label=getattr(column.label, language), type="number")
            if column.type == "number"
            else DisplayTextColumn(id=column.id, label=getattr(column.label, language), type="text")
            for column in definition.columns.for_kind(kind)
        ],
        items=rows,
        categories=[
            {"id": identifier, "name": getattr(name, language)}
            for identifier, name in sorted(dataset.categories.items())
        ],
    )


def recipe_tree(dataset: Dataset, identifier: int, language: Language) -> RecipeTree:
    recipes = {recipe.id: recipe for recipe in dataset.recipes}
    producers: dict[int, list[int]] = {}
    consumers: dict[int, list[int]] = {}
    for recipe in dataset.recipes:
        producers.setdefault(recipe.result, []).append(recipe.id)
        for ingredient in recipe.ingredients:
            if ingredient.reference.kind == "items":
                consumers.setdefault(ingredient.reference.id, []).append(recipe.id)
    nodes: dict[str, RecipeTreeNode] = {}
    edges: dict[tuple[str, str], RecipeTreeEdge] = {}
    ancestors: set[int] = set()
    descendants: set[int] = set()
    for upstream, reached in ((True, ancestors), (False, descendants)):
        pending = [identifier]
        while pending:
            current = pending.pop()
            if current in reached:
                continue
            reached.add(current)
            recipe = recipes[current]
            if upstream:
                for ingredient in recipe.ingredients:
                    if ingredient.reference.kind == "items":
                        pending.extend(producers.get(ingredient.reference.id, []))
            else:
                pending.extend(consumers.get(recipe.result, []))
    for current in sorted(ancestors | descendants):
        recipe = recipes[current]
        target = f"recipes:{current}"
        nodes[target] = RecipeTreeNode(
            key=target, kind="recipes", id=current, name=getattr(recipe.name, language)
        )
        for ingredient in recipe.ingredients:
            reference = ingredient.reference
            sources = producers.get(reference.id, []) if reference.kind == "items" else []
            for source_id in sources:
                if not (
                    (current in ancestors and source_id in ancestors)
                    or (current in descendants and source_id in descendants)
                ):
                    continue
                source = f"recipes:{source_id}"
                source_recipe = recipes[source_id]
                nodes[source] = RecipeTreeNode(
                    key=source,
                    kind="recipes",
                    id=source_id,
                    name=getattr(source_recipe.name, language),
                )
                pair = (source, target)
                if pair in edges:
                    edges[pair].quantity += ingredient.quantity
                else:
                    edges[pair] = RecipeTreeEdge(
                        source=source, target=target, quantity=ingredient.quantity
                    )
    items = {item.id: item for item in dataset.items}
    for node in nodes.values():
        node.categories = [
            DisplayCategory(id=category, name=getattr(dataset.categories[category], language))
            for category in items[recipes[node.id].result].categories
        ]
    return RecipeTree(nodes=list(nodes.values()), edges=list(edges.values()))


def get_detail(game_id: str, kind: DataKind, identifier: int, language: Language) -> DetailResponse:
    get_game(game_id)
    definition, dataset = load_dataset(game_id)
    entity = next((value for value in getattr(dataset, kind) if value.id == identifier), None)
    if entity is None:
        raise FileNotFoundError("データが見つかりません。")
    related: dict[DetailRelation, list[DetailLink]] = {}

    def add(relation: DetailRelation, category: DataKind, target: int) -> None:
        value = next((value for value in getattr(dataset, category) if value.id == target), None)
        links = related.setdefault(relation, [])
        if (
            value is not None
            and not (category == kind and target == identifier)
            and not any(link.kind == category and link.id == target for link in links)
        ):
            links.append(DetailLink(kind=category, id=target, name=getattr(value.name, language)))

    for recipe in dataset.recipes:
        if kind == "items":
            if recipe.result == identifier:
                add("acquisition", "recipes", recipe.id)
            if any(
                ingredient.reference.kind == "items" and ingredient.reference.id == identifier
                for ingredient in recipe.ingredients
            ):
                add("used_in", "recipes", recipe.id)
    for area in dataset.maps:
        if kind == "maps" and area.id == identifier:
            for target in area.items:
                add("gathered_items", "items", target)
            for target in area.monsters:
                add("encounters", "monsters", target)
        if kind == "items" and identifier in area.items:
            add("acquisition", "maps", area.id)
        if kind == "monsters" and identifier in area.monsters:
            add("locations", "maps", area.id)
    for monster in dataset.monsters:
        for drop in monster.drops:
            if kind == "monsters" and monster.id == identifier and drop.item is not None:
                add("drops", "items", drop.item)
            if kind == "items" and drop.item == identifier:
                add("acquisition", "monsters", monster.id)
    data = get_data(game_id, kind, language)
    return DetailResponse(
        game=GameSummary(
            id=game_id,
            title=getattr(definition.title, language),
            series=getattr(definition.series, language),
        ),
        kind=kind,
        name=getattr(entity.name, language),
        columns=data.columns,
        item=display_row(dataset, entity, language),
        related=related,
        recipe_tree=recipe_tree(dataset, identifier, language) if kind == "recipes" else None,
    )


def search_game(game_id: str, query: str, category: str, language: str, limit: int) -> list[dict]:
    get_game(game_id)
    path = database_path(game_id)
    if not path.is_file():
        raise FileNotFoundError("作品のデータがありません。")
    with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as connection:
        has_records = (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='records'"
            ).fetchone()
            is not None
        )
    if has_records:
        return search_index(query, category, language, limit, database=path)
    from .core import VALID_CATEGORIES, VALID_LANGUAGES

    if category not in VALID_CATEGORIES or language not in VALID_LANGUAGES:
        raise ValueError("検索フィルターが不正です。")
    _, dataset = load_dataset(game_id)
    languages = ("ja", "en", "zh") if language == "all" else (language,)
    result: list[dict] = []
    for kind in DATA_KINDS:
        for entity in getattr(dataset, kind):
            for column_id, values in entity.cells.items():
                for locale in languages:
                    cell = values.get(locale)
                    record_category = "name_candidate" if column_id == "name" else "text"
                    if (
                        cell
                        and cell.value is not None
                        and (category == "all" or category == record_category)
                        and query.casefold() in str(cell.value).casefold()
                    ):
                        result.append(
                            {
                                "id": entity.id,
                                "kind": kind,
                                "category": record_category,
                                "language": locale,
                                "text": str(cell.value),
                                "source": column_id,
                            }
                        )
                        if len(result) >= max(1, min(limit, 1000)):
                            return result
    return result


def export_game(game_id: str) -> dict[str, str]:
    get_game(game_id)
    definition, dataset = load_dataset(game_id)
    directory = game_directory(game_id) / "export"
    directory.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for kind in DATA_KINDS:
        path = directory / f"{kind}.csv"
        fields = [
            (column.id, language)
            for column in definition.columns.for_kind(kind)
            for language in ("ja", "en", "zh")
        ]
        with path.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream)
            writer.writerow(
                [
                    "id",
                    *(f"{key}_{language}" for key, language in fields),
                    "attributes",
                    "references",
                ]
            )
            for entity in getattr(dataset, kind):
                writer.writerow(
                    [
                        entity.id,
                        *(entity.cells[key][language].value for key, language in fields),
                        entity.model_dump_json(include={"attributes"}),
                        entity.model_dump_json(exclude={"id", "name", "cells", "attributes"}),
                    ]
                )
        outputs[kind] = str(path)
    with closing(
        sqlite3.connect(f"file:{database_path(game_id).as_posix()}?mode=ro", uri=True)
    ) as connection:
        tables = [
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        for table in tables:
            if table == "game_dataset" or table.startswith("sqlite_"):
                continue
            identifier = '"' + table.replace('"', '""') + '"'
            path = directory / f"source-{table}.csv"
            cursor = connection.execute(f"SELECT * FROM {identifier}")
            with path.open("w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.writer(stream)
                writer.writerow([column[0] for column in cursor.description])
                writer.writerows(cursor)
            outputs[f"source-{table}"] = str(path)
    return outputs
