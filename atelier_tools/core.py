from __future__ import annotations

import csv
import json
import logging
import os
import re
import sqlite3
import struct
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = PROJECT_ROOT / "data"
LOG_ROOT = PROJECT_ROOT / "logs"
DB_PATH = DATA_ROOT / "meruru.sqlite3"
SUMMARY_PATH = DATA_ROOT / "summary.json"

PRINTABLE_RUN = re.compile(rb"[\x20-\x7e\x80-\xbf\xc2-\xf4]{2,4096}")
KANA_RE = re.compile(r"[\u3040-\u30ff]")
CJK_RE = re.compile(r"[\u3400-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]")
ALLOWED_EAST_ASIAN_RE = re.compile(r"^[\x20-\x7e\u3000-\u30ff\u3400-\u9fff\uff00-\uffef]+$")
ASSET_RE = re.compile(r"(?i)(^|[\\/])[^\\/]+\.(pssg|g1t|dds|gz|ebm|emd|xml|wmv|hkx|ktx)$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_:\-./\\]{2,}$")


@dataclass(slots=True)
class Record:
    kind: str
    category: str
    language: str
    text: str
    source: str
    offset: int
    section: str | None
    edition: str
    metadata: dict | None = None


@dataclass(slots=True)
class Installation:
    is_valid: bool
    game_path: str | None
    japanese_exe: str | None
    english_exe: str | None
    event_directories: int
    issues: list[str]


def ensure_workspace() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    LOG_ROOT.mkdir(parents=True, exist_ok=True)


def configure_logging() -> None:
    ensure_workspace()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_ROOT / "atelier-tools.log", encoding="utf-8")],
        force=True,
    )


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


def read_u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise ValueError(f"32-bit value outside file at {offset}")
    return struct.unpack_from("<I", data, offset)[0]


def pe_sections(data: bytes) -> list[dict]:
    if len(data) < 512 or data[:2] != b"MZ":
        raise ValueError("Not a PE file")
    pe_offset = read_u32(data, 0x3C)
    if data[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise ValueError("Invalid PE signature")
    section_count = struct.unpack_from("<H", data, pe_offset + 6)[0]
    optional_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
    table_offset = pe_offset + 24 + optional_size
    result = []
    for index in range(section_count):
        offset = table_offset + 40 * index
        if offset + 40 > len(data):
            raise ValueError("Broken PE section table")
        result.append(
            {
                "name": data[offset : offset + 8].rstrip(b"\0").decode("ascii", "replace"),
                "virtual_size": read_u32(data, offset + 8),
                "virtual_address": read_u32(data, offset + 12),
                "raw_size": read_u32(data, offset + 16),
                "raw_offset": read_u32(data, offset + 20),
            }
        )
    return result


def text_language(text: str) -> str:
    has_kana = bool(KANA_RE.search(text))
    has_cjk = bool(CJK_RE.search(text))
    has_latin = bool(LATIN_RE.search(text))
    if (has_kana or has_cjk) and has_latin:
        return "mixed"
    if has_kana:
        return "ja"
    if has_cjk:
        return "zh"
    if has_latin:
        return "en"
    return "und"


def text_category(text: str, source_kind: str) -> str:
    if source_kind == "ebm":
        return "event"
    if ASSET_RE.search(text):
        return "asset"
    if "<CR>" in text or re.search(r"<CL[A-Z]+>", text) or len(text) >= 48 or re.search(r"[。！？.!?]$", text):
        return "description"
    if IDENTIFIER_RE.fullmatch(text) and (
        re.search(r"[_:/\\.]|[a-z][A-Z]", text) or (text.isupper() and len(text) >= 3)
    ):
        return "identifier"
    language = text_language(text)
    if language in {"ja", "zh"} and 2 <= len(text) <= 28 and not re.search(r'[\s<>「」『』【】（）()、。！？!?]', text):
        return "name_candidate"
    if language == "en" and 2 <= len(text) <= 48 and re.fullmatch(r"[A-Z][A-Za-z0-9'’&+\-]*(?: [A-Za-z0-9'’&+\-]+){0,7}", text):
        return "name_candidate"
    return "text"


def is_text_candidate(text: str, minimum_length: int = 2) -> bool:
    if not minimum_length <= len(text) <= 2048:
        return False
    if text.isascii():
        return len(text) >= 3 and bool(re.search(r"[A-Za-z]{2}|[0-9]{3}", text)) and text.isprintable()
    return bool(KANA_RE.search(text) or CJK_RE.search(text)) and bool(ALLOWED_EAST_ASIAN_RE.fullmatch(text))


def extract_pe_strings(path: Path, relative_source: str, edition: str) -> Iterator[Record]:
    data = path.read_bytes()
    for section in pe_sections(data):
        if section["name"] not in {".rdata", ".data"}:
            continue
        start = section["raw_offset"]
        end = min(len(data), start + section["raw_size"])
        if start < 0 or start >= len(data):
            continue
        for match in PRINTABLE_RUN.finditer(data, start, end):
            try:
                text = match.group().decode("utf-8").strip()
            except UnicodeDecodeError:
                continue
            if not is_text_candidate(text):
                continue
            yield Record(
                "pe_string",
                text_category(text, "pe"),
                text_language(text),
                text,
                relative_source,
                match.start(),
                section["name"],
                edition,
            )


def find_ebm_layout(data: bytes, count: int) -> tuple[int, int] | None:
    for duration1 in (0, 2):
        for duration2 in (0, 1, 2):
            position = 4
            valid = True
            for _ in range(count):
                header_words = 9 + duration1
                if position + 4 * header_words > len(data):
                    valid = False
                    break
                length = read_u32(data, position + 4 * (8 + duration1))
                text_offset = position + 4 * header_words
                if not 0 < length <= 2048 or text_offset + length + 4 * duration2 > len(data):
                    valid = False
                    break
                raw = data[text_offset : text_offset + length]
                if not raw.endswith(b"\0") or b"\0" in raw[:-1]:
                    valid = False
                    break
                try:
                    raw[:-1].decode("utf-8")
                except UnicodeDecodeError:
                    valid = False
                    break
                position = text_offset + length + 4 * duration2
            if valid:
                return duration1, duration2
    return None


def read_ebm(path: Path, relative_source: str, edition: str) -> Iterator[Record]:
    data = path.read_bytes()
    if len(data) < 4:
        return
    signed_count = struct.unpack_from("<i", data)[0]
    count = abs(signed_count)
    if count > 100_000:
        return
    layout = find_ebm_layout(data, count)
    if layout is None:
        return
    duration1, duration2 = layout
    position = 4
    for record_index in range(count):
        values = struct.unpack_from(f"<{9 + duration1}I", data, position)
        length = values[8 + duration1]
        text_offset = position + 4 * len(values)
        text = data[text_offset : text_offset + length - 1].decode("utf-8")
        metadata = {
            "record": record_index,
            "type": values[0],
            "voice_id": values[1],
            "name_id": values[3],
            "extra_id": values[4],
            "expression_id": values[5],
            "message_id": values[6 + duration1],
        }
        yield Record("event_message", "event", "ja" if edition == "JP" else "en", text, relative_source, text_offset, None, edition, metadata)
        position = text_offset + length + 4 * duration2


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


def _record_tuple(record: Record) -> tuple:
    return (
        record.kind,
        record.category,
        record.language,
        record.text,
        record.source,
        record.offset,
        record.section,
        record.edition,
        json.dumps(record.metadata, ensure_ascii=False, separators=(",", ":")) if record.metadata else None,
    )


def _insert_records(connection: sqlite3.Connection, records: Iterable[Record], counts: Counter) -> int:
    sql = "INSERT INTO records(kind,category,language,text,source,offset,section,edition,metadata_json) VALUES(?,?,?,?,?,?,?,?,?)"
    batch: list[tuple] = []
    inserted = 0
    for record in records:
        counts[record.category] += 1
        batch.append(_record_tuple(record))
        if len(batch) >= 2000:
            connection.executemany(sql, batch)
            inserted += len(batch)
            batch.clear()
    if batch:
        connection.executemany(sql, batch)
        inserted += len(batch)
    return inserted


def build_index(game_path: str | Path | None = None) -> dict:
    from .meruru import extract_structured_data

    ensure_workspace()
    configure_logging()
    installation = diagnose(game_path)
    if not installation.is_valid:
        raise ValueError(" ".join(installation.issues))
    root = Path(installation.game_path)
    temporary = DATA_ROOT / "meruru.sqlite3.building"
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
        structured = extract_structured_data(Path(installation.japanese_exe), Path(installation.english_exe) if installation.english_exe else None)
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
    os.replace(temporary, DB_PATH)
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
        "database": str(DB_PATH.relative_to(PROJECT_ROOT)),
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    logging.info("Index complete: %d records", total)
    return summary


VALID_CATEGORIES = {"all", "name_candidate", "description", "event", "asset", "identifier", "text"}
VALID_LANGUAGES = {"all", "ja", "en", "zh", "mixed", "und"}


def search_index(query: str = "", category: str = "all", language: str = "all", limit: int = 500) -> list[dict]:
    if not DB_PATH.is_file():
        raise FileNotFoundError("インデックスがありません。先にデータを抽出してください。")
    if category not in VALID_CATEGORIES or language not in VALID_LANGUAGES:
        raise ValueError("検索フィルターが不正です。")
    limit = max(1, min(int(limit), 1000))
    clauses: list[str] = []
    parameters: list[object] = []
    if category != "all":
        clauses.append("category = ?")
        parameters.append(category)
    if language != "all":
        clauses.append("language = ?")
        parameters.append(language)
    if query:
        clauses.append("instr(lower(text), lower(?)) > 0")
        parameters.append(query)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    sql = f"SELECT id,kind,category,language,text,source,offset,section,edition,metadata_json FROM records{where} ORDER BY id LIMIT ?"
    parameters.append(limit)
    connection = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(sql, parameters).fetchall()
    finally:
        connection.close()
    result = []
    for row in rows:
        item = dict(row)
        metadata_json = item.pop("metadata_json")
        item["metadata"] = json.loads(metadata_json) if metadata_json else None
        result.append(item)
    return result


def read_summary() -> dict | None:
    if not SUMMARY_PATH.is_file():
        return None
    return json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))


def search_structured(kind: str, query: str = "", language: str = "ja") -> list[dict]:
    if not DB_PATH.is_file():
        raise FileNotFoundError("インデックスがありません。先にデータを抽出してください。")
    if kind not in {"items", "recipes", "traits", "maps"}:
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
    connection = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
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


def export_csv() -> dict:
    if not DB_PATH.is_file():
        raise FileNotFoundError("インデックスがありません。先にデータを抽出してください。")
    outputs = {
        "all_data": DATA_ROOT / "meruru-data.csv",
        "name_candidates": DATA_ROOT / "meruru-name-candidates.csv",
        "events": DATA_ROOT / "meruru-events.csv",
        "items": DATA_ROOT / "meruru-items.csv",
        "item_categories": DATA_ROOT / "meruru-item-categories.csv",
        "recipes": DATA_ROOT / "meruru-recipes.csv",
        "recipe_ingredients": DATA_ROOT / "meruru-recipe-ingredients.csv",
        "traits": DATA_ROOT / "meruru-traits.csv",
        "maps": DATA_ROOT / "meruru-maps.csv",
        "monsters": DATA_ROOT / "meruru-monsters.csv",
        "map_items": DATA_ROOT / "meruru-map-items.csv",
        "map_monsters": DATA_ROOT / "meruru-map-monsters.csv",
    }
    connection = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    try:
        queries = {
            "all_data": "SELECT kind,category,language,text,source,offset,section,edition FROM records ORDER BY id",
            "name_candidates": "SELECT kind,category,language,text,source,offset,section,edition FROM records WHERE category='name_candidate' ORDER BY id",
            "events": "SELECT kind,category,language,text,source,offset,section,edition FROM records WHERE category='event' ORDER BY id",
            "items": "SELECT game_item_id,kind,name_ja,name_en,name_zh,value,level FROM items ORDER BY game_item_id",
            "item_categories": "SELECT item_categories.item_id,item_categories.slot,categories.name_ja,categories.name_en,categories.name_zh,item_categories.value FROM item_categories JOIN categories ON categories.category_id=item_categories.category_id ORDER BY item_categories.item_id,item_categories.slot",
            "recipes": "SELECT recipes.recipe_id,items.name_ja,items.name_en,items.name_zh,items.level,items.value,recipes.days FROM recipes JOIN items ON items.game_item_id=recipes.item_id ORDER BY recipes.recipe_id",
            "recipe_ingredients": "SELECT recipe_ingredients.recipe_id,recipe_ingredients.slot,recipe_ingredients.reference_type,recipe_ingredients.reference_id,CASE WHEN recipe_ingredients.reference_type='category' THEN categories.name_ja ELSE ingredient_items.name_ja END AS name_ja,CASE WHEN recipe_ingredients.reference_type='category' THEN categories.name_en ELSE ingredient_items.name_en END AS name_en,CASE WHEN recipe_ingredients.reference_type='category' THEN categories.name_zh ELSE ingredient_items.name_zh END AS name_zh,recipe_ingredients.quantity FROM recipe_ingredients LEFT JOIN categories ON recipe_ingredients.reference_type='category' AND categories.category_id=recipe_ingredients.reference_id LEFT JOIN items AS ingredient_items ON recipe_ingredients.reference_type='item' AND ingredient_items.game_item_id=recipe_ingredients.reference_id ORDER BY recipe_ingredients.recipe_id,recipe_ingredients.slot",
            "traits": "SELECT trait_id,name_ja,name_en,name_zh,description_ja,description_en,description_zh,cost FROM traits ORDER BY trait_id",
            "maps": "SELECT map_id,name_ja,name_en,name_zh,alternate_name_ja,alternate_name_en,alternate_name_zh,description_ja,description_en,description_zh FROM maps ORDER BY map_id",
            "monsters": "SELECT monster_id,name_ja,name_en,name_zh,level FROM monsters ORDER BY monster_id",
            "map_items": "SELECT map_items.map_id,maps.name_ja AS map_name_ja,map_items.item_id,items.name_ja AS item_name_ja FROM map_items JOIN maps ON maps.map_id=map_items.map_id JOIN items ON items.game_item_id=map_items.item_id ORDER BY map_items.map_id,map_items.item_id",
            "map_monsters": "SELECT map_monsters.map_id,maps.name_ja AS map_name_ja,map_monsters.monster_id,monsters.name_ja AS monster_name_ja FROM map_monsters JOIN maps ON maps.map_id=map_monsters.map_id JOIN monsters ON monsters.monster_id=map_monsters.monster_id ORDER BY map_monsters.map_id,map_monsters.monster_id",
        }
        for key, path in outputs.items():
            cursor = connection.execute(queries[key])
            with path.open("w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.writer(stream)
                writer.writerow([column[0] for column in cursor.description])
                writer.writerows(cursor)
    finally:
        connection.close()
    return {key: str(path) for key, path in outputs.items()}


def installation_dict(installation: Installation) -> dict:
    return asdict(installation)
