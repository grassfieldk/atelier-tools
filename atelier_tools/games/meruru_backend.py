from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

from ..core import DATA_ROOT, DB_PATH, PROJECT_ROOT, SUMMARY_PATH, Installation, _insert_records, configure_logging, ensure_workspace, extract_pe_strings, read_ebm

def find_game_path() -> Path | None:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            steam_path = Path(winreg.QueryValueEx(key, "SteamPath")[0])
    except (OSError, ImportError):
        return None
    libraries = [steam_path]
    vdf = steam_path / "steamapps" / "libraryfolders.vdf"
    if vdf.is_file():
        text = vdf.read_text(encoding="utf-8", errors="replace")
        libraries.extend(Path(value.replace(r"\\", "\\")) for value in re.findall(r'^\s*"path"\s+"(.+)"', text, re.MULTILINE))
    for library in libraries:
        candidate = library / "steamapps" / "common" / "Atelier Meruru ~The Apprentice of Arland~ DX"
        if (candidate / "A13V_x64_Release.exe").is_file():
            return candidate
    return None


def diagnose(game_path: str | Path | None = None) -> Installation:
    path = Path(game_path) if game_path else find_game_path()
    if path is None:
        return Installation(False, None, None, None, 0, ["メルル DX のインストール先を検出できませんでした。"])
    path = path.resolve()
    jp = path / "A13V_x64_Release.exe"
    en = path / "A13V_x64_Release_EN.exe"
    issues: list[str] = []
    if not jp.is_file():
        issues.append("日本語版実行ファイル A13V_x64_Release.exe がありません。")
    if not (path / "Event").is_dir():
        issues.append("Event ディレクトリがありません。")
    event_count = sum((path / "Event" / name).is_dir() for name in ("event", "event_EN"))
    return Installation(
        not issues,
        str(path),
        str(jp) if jp.is_file() else None,
        str(en) if en.is_file() else None,
        event_count,
        issues,
    )



SCHEMA = """
CREATE TABLE records (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    category TEXT NOT NULL,
    language TEXT NOT NULL,
    text TEXT NOT NULL,
    source TEXT NOT NULL,
    offset INTEGER NOT NULL,
    section TEXT,
    edition TEXT NOT NULL,
    metadata_json TEXT
);
CREATE INDEX records_category_language ON records(category, language);
CREATE INDEX records_source_offset ON records(source, offset);
CREATE TABLE items (
    game_item_id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    name_ja TEXT NOT NULL,
    name_en TEXT NOT NULL,
    name_zh TEXT NOT NULL,
    value INTEGER NOT NULL,
    level INTEGER NOT NULL,
    type_code INTEGER NOT NULL,
    source_offset INTEGER NOT NULL
);
CREATE INDEX items_kind ON items(kind);
CREATE TABLE categories (
    category_id INTEGER PRIMARY KEY,
    name_ja TEXT NOT NULL,
    name_en TEXT NOT NULL,
    name_zh TEXT NOT NULL
);
CREATE TABLE item_categories (
    item_id INTEGER NOT NULL REFERENCES items(game_item_id),
    slot INTEGER NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(category_id),
    value INTEGER NOT NULL,
    PRIMARY KEY (item_id, slot)
);
CREATE TABLE recipes (
    recipe_id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES items(game_item_id),
    days REAL NOT NULL,
    source_offset INTEGER NOT NULL
);
CREATE TABLE recipe_ingredients (
    recipe_id INTEGER NOT NULL REFERENCES recipes(recipe_id),
    slot INTEGER NOT NULL,
    reference_type TEXT NOT NULL,
    reference_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    PRIMARY KEY (recipe_id, slot)
);
CREATE TABLE item_qualities (
    item_id INTEGER NOT NULL REFERENCES items(game_item_id),
    rank INTEGER NOT NULL,
    name_ja TEXT NOT NULL,
    name_en TEXT NOT NULL,
    name_zh TEXT NOT NULL,
    PRIMARY KEY (item_id, rank)
);
CREATE TABLE traits (
    trait_id INTEGER PRIMARY KEY,
    name_ja TEXT NOT NULL,
    name_en TEXT NOT NULL,
    name_zh TEXT NOT NULL,
    description_ja TEXT,
    description_en TEXT,
    description_zh TEXT,
    cost INTEGER NOT NULL,
    category_code INTEGER NOT NULL,
    applicability_flags INTEGER NOT NULL,
    source_offset INTEGER NOT NULL
);
CREATE TABLE maps (
    map_id INTEGER PRIMARY KEY,
    name_ja TEXT NOT NULL,
    name_en TEXT NOT NULL,
    name_zh TEXT NOT NULL,
    alternate_name_ja TEXT,
    alternate_name_en TEXT,
    alternate_name_zh TEXT,
    description_ja TEXT,
    description_en TEXT,
    description_zh TEXT,
    alternate_description_ja TEXT,
    alternate_description_en TEXT,
    alternate_description_zh TEXT,
    x REAL NOT NULL,
    y REAL NOT NULL,
    source_offset INTEGER NOT NULL
);
CREATE TABLE monsters (
    monster_id INTEGER PRIMARY KEY,
    name_ja TEXT NOT NULL,
    name_en TEXT NOT NULL,
    name_zh TEXT NOT NULL,
    level INTEGER NOT NULL,
    source_offset INTEGER NOT NULL
);
CREATE TABLE map_items (
    map_id INTEGER NOT NULL REFERENCES maps(map_id),
    item_id INTEGER NOT NULL REFERENCES items(game_item_id),
    PRIMARY KEY (map_id, item_id)
);
CREATE TABLE map_monsters (
    map_id INTEGER NOT NULL REFERENCES maps(map_id),
    monster_id INTEGER NOT NULL REFERENCES monsters(monster_id),
    PRIMARY KEY (map_id, monster_id)
);
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""



def build_index(game_path: str | Path | None = None, *, database: Path | None = None, summary_path: Path | None = None, analysis_root: Path | None = None) -> dict:
    from ..meruru import extract_structured_data

    ensure_workspace()
    configure_logging()
    destination = database or DB_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    summary_destination = summary_path or SUMMARY_PATH
    installation = diagnose(game_path)
    if not installation.is_valid:
        raise ValueError(" ".join(installation.issues))
    root = Path(installation.game_path)
    temporary = destination.with_suffix(".sqlite3.building")
    temporary.unlink(missing_ok=True)
    counts: Counter = Counter()
    total = 0
    logging.info("Index start")
    connection = sqlite3.connect(temporary)
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.executescript(SCHEMA)
        sources = [
            (installation.japanese_exe, "A13V_x64_Release.exe", "JP"),
            (installation.english_exe, "A13V_x64_Release_EN.exe", "EN"),
        ]
        for source_path, relative, edition in sources:
            if source_path:
                total += _insert_records(connection, extract_pe_strings(Path(source_path), relative, edition), counts)
        for directory, edition in (("event", "JP"), ("event_EN", "EN")):
            event_root = root / "Event" / directory
            if not event_root.is_dir():
                continue
            for path in event_root.rglob("*.ebm"):
                total += _insert_records(connection, read_ebm(path, str(path.relative_to(root)), edition), counts)
        structured = extract_structured_data(Path(installation.japanese_exe), Path(installation.english_exe) if installation.english_exe else None, analysis_root=analysis_root)
        connection.executemany(
            "INSERT INTO categories(category_id,name_ja,name_en,name_zh) "
            "VALUES(:category_id,:name_ja,:name_en,:name_zh)",
            structured["categories"],
        )
        connection.executemany(
            "INSERT INTO items(game_item_id,kind,name_ja,name_en,name_zh,value,level,type_code,source_offset) "
            "VALUES(:game_item_id,:kind,:name_ja,:name_en,:name_zh,:value,:level,:type_code,:source_offset)",
            structured["items"],
        )
        connection.executemany(
            "INSERT INTO item_categories(item_id,slot,category_id,value) VALUES(:item_id,:slot,:category_id,:value)",
            structured["item_categories"],
        )
        connection.executemany(
            "INSERT INTO recipes(recipe_id,item_id,days,source_offset) VALUES(:recipe_id,:item_id,:days,:source_offset)",
            structured["recipes"],
        )
        connection.executemany(
            "INSERT INTO recipe_ingredients(recipe_id,slot,reference_type,reference_id,quantity) "
            "VALUES(:recipe_id,:slot,:reference_type,:reference_id,:quantity)",
            structured["recipe_ingredients"],
        )
        connection.executemany(
            "INSERT INTO item_qualities(item_id,rank,name_ja,name_en,name_zh) VALUES(:item_id,:rank,:name_ja,:name_en,:name_zh)",
            structured["item_qualities"],
        )
        connection.executemany(
            "INSERT INTO traits(trait_id,name_ja,name_en,name_zh,description_ja,description_en,description_zh,cost,category_code,applicability_flags,source_offset) "
            "VALUES(:trait_id,:name_ja,:name_en,:name_zh,:description_ja,:description_en,:description_zh,:cost,:category_code,:applicability_flags,:source_offset)",
            structured["traits"],
        )
        connection.executemany(
            "INSERT INTO maps(map_id,name_ja,name_en,name_zh,alternate_name_ja,alternate_name_en,alternate_name_zh,description_ja,description_en,description_zh,alternate_description_ja,alternate_description_en,alternate_description_zh,x,y,source_offset) "
            "VALUES(:map_id,:name_ja,:name_en,:name_zh,:alternate_name_ja,:alternate_name_en,:alternate_name_zh,:description_ja,:description_en,:description_zh,:alternate_description_ja,:alternate_description_en,:alternate_description_zh,:x,:y,:source_offset)",
            structured["maps"],
        )
        connection.executemany(
            "INSERT INTO monsters(monster_id,name_ja,name_en,name_zh,level,source_offset) "
            "VALUES(:monster_id,:name_ja,:name_en,:name_zh,:level,:source_offset)",
            structured["monsters"],
        )
        connection.executemany(
            "INSERT INTO map_items(map_id,item_id) VALUES(:map_id,:item_id)",
            structured["map_items"],
        )
        connection.executemany(
            "INSERT INTO map_monsters(map_id,monster_id) VALUES(:map_id,:monster_id)",
            structured["map_monsters"],
        )
        generated_at = datetime.now().astimezone().isoformat()
        metadata = {
            "schema_version": "5",
            "generated_at": generated_at,
            "game": "Atelier Meruru ~The Apprentice of Arland~ DX",
            "read_only": "true",
            "total_records": str(total),
            "items": str(len(structured["items"])),
            "recipes": str(len(structured["recipes"])),
            "recipe_ingredients": str(len(structured["recipe_ingredients"])),
            "traits": str(len(structured["traits"])),
            "maps": str(len(structured["maps"])),
            "monsters": str(len(structured["monsters"])),
            "map_items": str(len(structured["map_items"])),
            "map_monsters": str(len(structured["map_monsters"])),
        }
        connection.executemany("INSERT INTO metadata(key,value) VALUES(?,?)", metadata.items())
        connection.commit()
        connection.execute("PRAGMA optimize")
    finally:
        connection.close()
    os.replace(temporary, destination)
    summary = {
        "schema_version": 5,
        "generated_at": generated_at,
        "game": "Atelier Meruru ~The Apprentice of Arland~ DX",
        "read_only": True,
        "total_records": total,
        "categories": dict(counts),
        "structured": {
            "items": len(structured["items"]),
            "recipes": len(structured["recipes"]),
            "recipe_ingredients": len(structured["recipe_ingredients"]),
            "traits": len(structured["traits"]),
            "maps": len(structured["maps"]),
            "monsters": len(structured["monsters"]),
            "map_items": len(structured["map_items"]),
            "map_monsters": len(structured["map_monsters"]),
        },
        "database": str(destination.relative_to(PROJECT_ROOT)),
    }
    summary_destination.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    logging.info("Index complete: %d records", total)
    return summary



def search_structured(kind: str, query: str = "", language: str = "ja", *, database: Path | None = None) -> list[dict]:
    database = database or DB_PATH
    if not database.is_file():
        raise FileNotFoundError("インデックスがありません。先にデータを抽出してください。")
    if kind not in {"items", "recipes", "traits", "maps", "monsters"}:
        raise ValueError("データ分類が不正です。")
    language = language if language in {"ja", "en", "zh"} else "ja"
    name_column = f"name_{language}"
    description_column = f"description_{language}"
    parameters: list[object] = []
    if kind == "items":
        sql = (
            f"SELECT items.game_item_id AS id, items.kind, items.{name_column} AS name, items.value, items.level, "
            f"(SELECT group_concat(category_name, '、') FROM ("
            f"SELECT categories.{name_column} AS category_name FROM item_categories "
            "JOIN categories ON categories.category_id=item_categories.category_id "
            "WHERE item_categories.item_id=items.game_item_id ORDER BY item_categories.slot)) AS categories "
            "FROM items"
        )
        if query:
            sql += f" WHERE instr(lower(items.{name_column}), lower(?)) > 0"
            parameters.append(query)
        sql += " ORDER BY items.game_item_id"
    elif kind == "recipes":
        sql = (
            f"SELECT recipes.recipe_id AS id, items.{name_column} AS name, items.level, items.value, recipes.days "
            "FROM recipes JOIN items ON items.game_item_id = recipes.item_id"
        )
        if query:
            sql += f" WHERE instr(lower(items.{name_column}), lower(?)) > 0"
            parameters.append(query)
        sql += " ORDER BY recipes.recipe_id"
    elif kind == "traits":
        sql = f"SELECT trait_id AS id, {name_column} AS name, {description_column} AS description, cost FROM traits"
        if query:
            sql += f" WHERE instr(lower({name_column}), lower(?)) > 0 OR instr(lower({description_column}), lower(?)) > 0"
            parameters.extend((query, query))
        sql += " ORDER BY trait_id"
    elif kind == "monsters":
        sql = f"SELECT monster_id AS id, {name_column} AS name, level FROM monsters"
        if query:
            sql += f" WHERE instr(lower({name_column}), lower(?)) > 0"
            parameters.append(query)
        sql += " ORDER BY monster_id"
    else:
        alternate_name_column = f"alternate_name_{language}"
        alternate_description_column = f"alternate_description_{language}"
        sql = (
            f"SELECT map_id AS id, {name_column} AS name, {alternate_name_column} AS alternate_name, "
            f"{description_column} AS description, {alternate_description_column} AS alternate_description, x, y FROM maps"
        )
        if query:
            sql += (
                f" WHERE instr(lower({name_column}), lower(?)) > 0 "
                f"OR instr(lower({alternate_name_column}), lower(?)) > 0 "
                f"OR instr(lower({description_column}), lower(?)) > 0 "
                f"OR instr(lower({alternate_description_column}), lower(?)) > 0"
            )
            parameters.extend((query, query, query, query))
        sql += " ORDER BY map_id"
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        result = [dict(row) for row in connection.execute(sql, parameters).fetchall()]
        if kind == "recipes" and result:
            recipe_ids = [item["id"] for item in result]
            placeholders = ",".join("?" for _ in recipe_ids)
            ingredient_sql = (
                f"SELECT recipe_ingredients.recipe_id,recipe_ingredients.slot,recipe_ingredients.reference_type,"
                f"recipe_ingredients.reference_id,recipe_ingredients.quantity,"
                f"CASE WHEN recipe_ingredients.reference_type='category' THEN categories.{name_column} "
                f"ELSE ingredient_items.{name_column} END AS name "
                "FROM recipe_ingredients "
                "LEFT JOIN categories ON recipe_ingredients.reference_type='category' "
                "AND categories.category_id=recipe_ingredients.reference_id "
                "LEFT JOIN items AS ingredient_items ON recipe_ingredients.reference_type='item' "
                "AND ingredient_items.game_item_id=recipe_ingredients.reference_id "
                f"WHERE recipe_ingredients.recipe_id IN ({placeholders}) "
                "ORDER BY recipe_ingredients.recipe_id,recipe_ingredients.slot"
            )
            grouped = {recipe_id: [] for recipe_id in recipe_ids}
            for row in connection.execute(ingredient_sql, recipe_ids):
                grouped[row["recipe_id"]].append(dict(row))
            for item in result:
                item["ingredients"] = grouped[item["id"]]
        if kind == "maps" and result:
            map_ids = [item["id"] for item in result]
            placeholders = ",".join("?" for _ in map_ids)
            item_sql = (
                f"SELECT map_items.map_id,items.game_item_id AS id,items.{name_column} AS name FROM map_items "
                "JOIN items ON items.game_item_id=map_items.item_id "
                f"WHERE map_items.map_id IN ({placeholders}) ORDER BY map_items.map_id,items.game_item_id"
            )
            monster_sql = (
                f"SELECT map_monsters.map_id,monsters.monster_id AS id,monsters.{name_column} AS name FROM map_monsters "
                "JOIN monsters ON monsters.monster_id=map_monsters.monster_id "
                f"WHERE map_monsters.map_id IN ({placeholders}) ORDER BY map_monsters.map_id,monsters.monster_id"
            )
            grouped_items = {map_id: [] for map_id in map_ids}
            grouped_monsters = {map_id: [] for map_id in map_ids}
            for row in connection.execute(item_sql, map_ids):
                grouped_items[row["map_id"]].append({"id": row["id"], "name": row["name"]})
            for row in connection.execute(monster_sql, map_ids):
                grouped_monsters[row["map_id"]].append({"id": row["id"], "name": row["name"]})
            for item in result:
                item["items"] = grouped_items[item["id"]]
                item["monsters"] = grouped_monsters[item["id"]]
        return result
    finally:
        connection.close()


