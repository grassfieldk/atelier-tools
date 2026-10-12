from __future__ import annotations

import csv
import sqlite3
from contextlib import closing
from pathlib import Path

from .core import search_index
from .games.base import ExtractionContext
from .games.registry import get_game, registered_games
from .models import DATA_KINDS, DataKind, DataResponse, DisplayNumberColumn, DisplayTextColumn, DisplayRow, GamesResponse, GameSummary, Language
from .storage import database_path, game_directory, load_dataset, save_dataset


def migrate_game(game_id: str) -> dict:
    from .core import DATA_ROOT, DB_PATH
    from .games.meruru import MeruruAdapter
    import shutil

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
    return GamesResponse(items=[
        GameSummary(id=adapter.definition.id, title=getattr(adapter.definition.title, language), series=getattr(adapter.definition.series, language))
        for adapter in registered_games()
        if database_path(adapter.definition.id).is_file()
    ])


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


def get_data(game_id: str, kind: DataKind, language: Language, query: str = "") -> DataResponse:
    get_game(game_id)
    definition, dataset = load_dataset(game_id)
    rows = [DisplayRow(id=entity.id, cells={key: values[language] for key, values in entity.cells.items()}) for entity in getattr(dataset, kind)]
    if query:
        normalized = query.casefold()
        rows = [row for row in rows if any(normalized in str(cell.value or "").casefold() for cell in row.cells.values())]
    return DataResponse(kind=kind, count=len(rows), columns=[DisplayNumberColumn(id=column.id, label=getattr(column.label, language), type="number") if column.type == "number" else DisplayTextColumn(id=column.id, label=getattr(column.label, language), type="text") for column in definition.columns.for_kind(kind)], items=rows)


def search_game(game_id: str, query: str, category: str, language: str, limit: int) -> list[dict]:
    get_game(game_id)
    path = database_path(game_id)
    if not path.is_file():
        raise FileNotFoundError("作品のデータがありません。")
    with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as connection:
        has_records = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='records'").fetchone() is not None
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
                    if cell and cell.value is not None and (category == "all" or category == record_category) and query.casefold() in str(cell.value).casefold():
                        result.append({"id": entity.id, "kind": kind, "category": record_category, "language": locale, "text": str(cell.value), "source": column_id})
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
        fields = [(column.id, language) for column in definition.columns.for_kind(kind) for language in ("ja", "en", "zh")]
        with path.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream)
            writer.writerow(["id", *(f"{key}_{language}" for key, language in fields), "attributes", "references"])
            for entity in getattr(dataset, kind):
                writer.writerow([entity.id, *(entity.cells[key][language].value for key, language in fields), entity.model_dump_json(include={"attributes"}), entity.model_dump_json(exclude={"id", "name", "cells", "attributes"})])
        outputs[kind] = str(path)
    with closing(sqlite3.connect(f"file:{database_path(game_id).as_posix()}?mode=ro", uri=True)) as connection:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
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
