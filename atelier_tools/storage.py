from __future__ import annotations

import json
import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from .core import DATA_ROOT
from .models import DATA_KINDS, Dataset, GameDefinition


def game_directory(game_id: str) -> Path:
    if not game_id or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in game_id
    ):
        raise ValueError("Invalid game ID")
    return DATA_ROOT / game_id


def database_path(game_id: str) -> Path:
    return game_directory(game_id) / "data.sqlite3"


def save_dataset(definition: GameDefinition, dataset: Dataset, source: Path | None = None) -> dict:
    for kind in DATA_KINDS:
        expected = {column.id: column.type for column in definition.columns.for_kind(kind)}
        for entity in getattr(dataset, kind):
            if set(entity.cells) != set(expected):
                raise ValueError(f"Column mismatch: {kind}/{entity.id}")
            for column_id, values in entity.cells.items():
                if set(values) != {"ja", "en", "zh"} or any(
                    cell.type != expected[column_id] for cell in values.values()
                ):
                    raise ValueError(f"Cell type mismatch: {kind}/{entity.id}/{column_id}")
    directory = game_directory(definition.id)
    directory.mkdir(parents=True, exist_ok=True)
    destination = database_path(definition.id)
    temporary = destination.with_suffix(".sqlite3.building")
    temporary.unlink(missing_ok=True)
    if source:
        shutil.copyfile(source, temporary)
    with closing(sqlite3.connect(temporary)) as connection:
        with connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS game_dataset (id INTEGER PRIMARY KEY CHECK(id=1), definition TEXT NOT NULL, dataset TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT OR REPLACE INTO game_dataset VALUES (1, ?, ?)",
                (definition.model_dump_json(), dataset.model_dump_json()),
            )
    os.replace(temporary, destination)
    summary = {
        "game_id": definition.id,
        "schema_version": 1,
        "structured": {kind: len(getattr(dataset, kind)) for kind in DATA_KINDS},
    }
    (directory / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def load_dataset(game_id: str) -> tuple[GameDefinition, Dataset]:
    path = database_path(game_id)
    if not path.is_file():
        raise FileNotFoundError("作品のデータがありません。先に移行または抽出してください。")
    with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as connection:
        row = connection.execute(
            "SELECT definition, dataset FROM game_dataset WHERE id=1"
        ).fetchone()
    if row is None:
        raise ValueError("作品のデータ契約がありません。")
    return GameDefinition.model_validate_json(row[0]), Dataset.model_validate_json(row[1])
