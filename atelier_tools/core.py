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
    from .games.meruru_backend import find_game_path as find

    return find()


def diagnose(game_path: str | Path | None = None) -> Installation:
    from .games.meruru_backend import diagnose as inspect

    return inspect(game_path)


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


def build_index(game_path: str | Path | None = None, **options) -> dict:
    from .games.meruru_backend import build_index as build

    return build(game_path, **options)


VALID_CATEGORIES = {"all", "name_candidate", "description", "event", "asset", "identifier", "text"}
VALID_LANGUAGES = {"all", "ja", "en", "zh", "mixed", "und"}


def search_index(query: str = "", category: str = "all", language: str = "all", limit: int = 500, *, database: Path | None = None) -> list[dict]:
    database = database or DB_PATH
    if not database.is_file():
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
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
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


def search_structured(kind: str, query: str = "", language: str = "ja", *, database: Path | None = None) -> list[dict]:
    from .games.meruru_backend import search_structured as search

    return search(kind, query, language, database=database or DB_PATH)


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
