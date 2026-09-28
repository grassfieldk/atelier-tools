from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path

from .core import pe_sections, read_u32


SYNTHESIS_STRIDE = 0xB8
MATERIAL_STRIDE = 0xA8
EQUIPMENT_STRIDE = 0xA0
TRAIT_STRIDE = 0x40
RECIPE_STRIDE = 0x190
MAP_STRIDE = 0x68
MAP_COUNT = 45
MONSTER_STRIDE = 0x38
MONSTER_CHARACTER_STRIDE = 0x44
MONSTER_CHARACTER_TABLE = 0xE31B48
COLLECT_PLACEMENT_STRIDE = 0x48
COLLECT_POOL_STRIDE = 0x40
ENEMY_TEXT_BASE = 0x140001000
ENEMY_FUNCTION_START = 0x140313040
ENEMY_RECORDS_END = 0x1403327FC
ENEMY_RECORD_OFFSET = 0x30
ENEMY_RECORD_STRIDE = 0x70
ENEMY_RECORD_COUNT = 0x153
SYNTHESIS_COUNT = 180
EQUIPMENT_COUNT = 47
RECIPE_RECORD_COUNT = 230
MATERIAL_ITEM_BASE = 0xE3
MARKUP_RE = re.compile(r"<[^>]+>")
POINT_INDEX_RE = re.compile(r"point_(SMALL|EXTRA)_(\d+)", re.IGNORECASE)


def _map_field_ids(executable: Executable, map_table: int, map_id: int) -> tuple[int, ...]:
    big_fields = {
        0: (12,),
        1: (13, 14),
        2: (15, 16),
        3: (17,),
        4: (18,),
        5: (19, 20, 21, 22, 23),
        6: (24,),
        7: (25, 26, 27),
        8: (25, 26, 27),
        9: (25, 26, 27),
        10: (25, 26, 27),
        11: (25, 26, 27),
        12: (28, 29, 30, 31),
        13: (32, 33, 34, 35, 36),
    }
    if map_id in big_fields:
        return big_fields[map_id]
    special_fields = {
        42: (65,),
        43: (66, 67),
        44: (77, 78, 79, 80, 81),
    }
    if map_id in special_fields:
        return special_fields[map_id]
    asset = record_text(executable, map_table + map_id * MAP_STRIDE, 0x50) or ""
    match = POINT_INDEX_RE.search(asset)
    if not match:
        return ()
    point_kind, point_index = match.groups()
    return (37 + int(point_index),) if point_kind.upper() == "SMALL" else (77 + int(point_index),)


def _collect_associations(path: Path) -> dict[int, set[int]]:
    if not path.is_file():
        return {}
    data = path.read_bytes()
    field_pools: dict[int, set[int]] = {}
    placement_end = min(len(data), 0xE230)
    for offset in range(0x10, placement_end - COLLECT_PLACEMENT_STRIDE + 1, COLLECT_PLACEMENT_STRIDE):
        pool_id, field_id = struct.unpack_from("<I16xI", data, offset)
        if pool_id <= 252 and 12 <= field_id <= 81:
            field_pools.setdefault(field_id, set()).add(pool_id)
    pool_items: dict[int, set[int]] = {}
    for offset in range(0xE230, len(data) - COLLECT_POOL_STRIDE + 1, COLLECT_POOL_STRIDE):
        pool_id, item_id = struct.unpack_from("<II", data, offset)
        if pool_id <= 252:
            pool_items.setdefault(pool_id, set()).add(item_id)
    return {
        field_id: {item_id for pool_id in pool_ids for item_id in pool_items.get(pool_id, ())}
        for field_id, pool_ids in field_pools.items()
    }


def _enemy_placement_records(path: Path) -> list[list[int | None]]:
    if not path.is_file():
        return []
    data = path.read_bytes()
    start = ENEMY_FUNCTION_START - ENEMY_TEXT_BASE
    end = ENEMY_RECORDS_END - ENEMY_TEXT_BASE
    code = data[start:end]
    records: list[list[int | None]] = [[None] * (ENEMY_RECORD_STRIDE // 4) for _ in range(ENEMY_RECORD_COUNT)]
    position = 0
    while position < len(code) - 11:
        displacement = None
        immediate = None
        if code[position : position + 3] == b"\xc7\x44\x24":
            displacement = code[position + 3]
            immediate = struct.unpack_from("<I", code, position + 4)[0]
            position += 8
        elif code[position : position + 3] == b"\xc7\x84\x24":
            displacement = struct.unpack_from("<I", code, position + 3)[0]
            immediate = struct.unpack_from("<I", code, position + 7)[0]
            position += 11
        else:
            position += 1
        if displacement is None or immediate is None:
            continue
        relative = displacement - ENEMY_RECORD_OFFSET
        if not 0 <= relative < ENEMY_RECORD_COUNT * ENEMY_RECORD_STRIDE:
            continue
        record_index, field_offset = divmod(relative, ENEMY_RECORD_STRIDE)
        if field_offset % 4 == 0:
            records[record_index][field_offset // 4] = immediate
    return records


def _monster_associations(executable: Executable, monster_count: int, text_path: Path) -> dict[int, set[int]]:
    monster_by_character = {
        read_u32(executable.data, MONSTER_CHARACTER_TABLE + monster_id * MONSTER_CHARACTER_STRIDE + 4): monster_id
        for monster_id in range(monster_count)
    }
    result: dict[int, set[int]] = {}
    for words in _enemy_placement_records(text_path):
        character_id = words[1]
        field_id = words[5]
        if character_id in monster_by_character and field_id is not None:
            result.setdefault(field_id, set()).add(monster_by_character[character_id])
    return result


@dataclass(slots=True)
class Executable:
    path: Path
    data: bytes
    image_base: int
    sections: list[dict]


def open_executable(path: Path) -> Executable:
    data = path.read_bytes()
    pe_offset = read_u32(data, 0x3C)
    optional_offset = pe_offset + 24
    if struct.unpack_from("<H", data, optional_offset)[0] != 0x20B:
        raise ValueError(f"PE32+ 形式ではありません: {path.name}")
    image_base = struct.unpack_from("<Q", data, optional_offset + 24)[0]
    return Executable(path, data, image_base, pe_sections(data))


def offset_to_rva(executable: Executable, offset: int) -> int | None:
    for section in executable.sections:
        start = section["raw_offset"]
        if start <= offset < start + section["raw_size"]:
            return section["virtual_address"] + offset - start
    return None


def rva_to_offset(executable: Executable, rva: int) -> int | None:
    for section in executable.sections:
        start = section["virtual_address"]
        size = max(section["virtual_size"], section["raw_size"])
        if start <= rva < start + size:
            offset = section["raw_offset"] + rva - start
            if offset < section["raw_offset"] + section["raw_size"]:
                return offset
    return None


def pointer_text(executable: Executable, pointer: int) -> str | None:
    if pointer < executable.image_base:
        return None
    offset = rva_to_offset(executable, pointer - executable.image_base)
    if offset is None:
        return None
    end = executable.data.find(b"\0", offset, min(len(executable.data), offset + 4096))
    if end < 0:
        return None
    try:
        return executable.data[offset:end].decode("utf-8")
    except UnicodeDecodeError:
        return None


def record_text(executable: Executable, offset: int, field_offset: int = 0) -> str | None:
    pointer = struct.unpack_from("<Q", executable.data, offset + field_offset)[0]
    return pointer_text(executable, pointer)


def find_table(executable: Executable, anchors: tuple[str, ...], stride: int) -> int:
    first = anchors[0].encode("utf-8") + b"\0"
    position = 0
    while True:
        position = executable.data.find(first, position)
        if position < 0:
            break
        rva = offset_to_rva(executable, position)
        if rva is not None:
            pointer = struct.pack("<Q", executable.image_base + rva)
            reference = 0
            while True:
                reference = executable.data.find(pointer, reference)
                if reference < 0:
                    break
                if all(record_text(executable, reference + index * stride) == text for index, text in enumerate(anchors)):
                    return reference
                reference += 1
        position += 1
    raise ValueError(f"データテーブルを検出できません: {', '.join(anchors)}")


def find_locale_tables(executable: Executable, first_table: int, stride: int, count: int = 4) -> list[int]:
    signatures = [executable.data[first_table + index * stride + 8 : first_table + index * stride + 0x30] for index in range(3)]
    starts = []
    position = 0
    while True:
        position = executable.data.find(signatures[0], position)
        if position < 0:
            break
        candidate = position - 8
        if candidate >= 0 and all(
            executable.data[candidate + index * stride + 8 : candidate + index * stride + 0x30] == signature
            for index, signature in enumerate(signatures)
        ):
            starts.append(candidate)
        position += 1
    starts = sorted(set(starts))
    if len(starts) < count:
        raise ValueError("言語別データテーブルを検出できません")
    return starts[:count]


def find_map_tables(executable: Executable, first_table: int, count: int = 4) -> list[int]:
    signatures = [executable.data[first_table + index * MAP_STRIDE + 0x10 : first_table + index * MAP_STRIDE + 0x38] for index in range(3)]
    starts = []
    position = 0
    while True:
        position = executable.data.find(signatures[0], position)
        if position < 0:
            break
        candidate = position - 0x10
        if candidate >= 0 and all(
            executable.data[candidate + index * MAP_STRIDE + 0x10 : candidate + index * MAP_STRIDE + 0x38] == signature
            for index, signature in enumerate(signatures)
        ):
            starts.append(candidate)
        position += 1
    starts = sorted(set(starts))
    if len(starts) < count:
        raise ValueError("言語別マップデータテーブルを検出できません")
    return starts[:count]


def find_recipe_table(executable: Executable) -> int:
    marker = struct.pack("<I", 0)
    position = 0
    while True:
        position = executable.data.find(marker, position)
        if position < 0:
            break
        if (
            read_u32(executable.data, position + RECIPE_STRIDE) == 1
            and read_u32(executable.data, position + RECIPE_STRIDE * 2) == 2
            and read_u32(executable.data, position + 0x24) == 0xE6
            and read_u32(executable.data, position + 0x28) == 2
            and read_u32(executable.data, position + RECIPE_STRIDE + 0x24) == 0xFC
        ):
            return position
        position += 1
    raise ValueError("レシピデータテーブルを検出できません")


def clean_description(text: str | None) -> str | None:
    if not text:
        return None
    text = text.replace("<CR>", "\n").replace("※合成※", "合成: ")
    return MARKUP_RE.sub("", text).strip()


def _words(executable: Executable, offset: int, size: int) -> tuple[int, ...]:
    return struct.unpack_from(f"<{size // 4}I", executable.data, offset)


def _names(executable: Executable, tables: list[int], index: int, stride: int, field_offset: int = 0) -> dict[str, str]:
    values = [record_text(executable, table + index * stride, field_offset) for table in tables]
    if any(value is None for value in values):
        raise ValueError(f"名称を読み取れません: index={index}")
    return {"name_ja": values[0], "name_en": values[1], "name_zh": values[3]}


def _quality_names(executable: Executable, offset: int, stride: int, first_pointer: int = 0x50) -> list[str]:
    result = []
    for field_offset in range(first_pointer, stride, 0x10):
        text = record_text(executable, offset, field_offset)
        if text:
            result.append(text)
    return result


def _append_qualities(
    result: list[dict], executable: Executable, tables: list[int], index: int, stride: int, item_id: int, first_pointer: int = 0x50
) -> None:
    localized = [_quality_names(executable, table + index * stride, stride, first_pointer) for table in tables]
    for rank, values in enumerate(zip(localized[0], localized[1], localized[3])):
        result.append({"item_id": item_id, "rank": rank, "name_ja": values[0], "name_en": values[1], "name_zh": values[2]})


def _append_item_categories(result: list[dict], item_id: int, words: tuple[int, ...]) -> None:
    for slot, word_index in enumerate(range(7, 19, 2)):
        category_id = words[word_index]
        if category_id == 0xFFFFFFFF or category_id >= 35:
            continue
        result.append({"item_id": item_id, "slot": slot, "category_id": category_id, "value": words[word_index + 1]})


def _category_tables(executable: Executable) -> tuple[list[int], int]:
    japanese = find_table(executable, ("（薬の材料）", "（中和剤）", "（調味料）"), 8)
    count = 0
    while record_text(executable, japanese + count * 8):
        count += 1
    tables = [japanese]
    for _ in range(3):
        tables.append(tables[-1] + (count + 1) * 8)
    return tables, count


def extract_structured_data(japanese_path: Path, english_path: Path | None = None) -> dict[str, list[dict]]:
    executable = open_executable(japanese_path)
    synthesis = find_table(executable, ("クラフト", "フラム", "レヘルン"), SYNTHESIS_STRIDE)
    materials = find_table(executable, ("プレイン草", "マジックグラス", "うに"), MATERIAL_STRIDE)
    equipment = find_table(executable, ("見習いの杖", "開拓民の杖", "宝石の杖"), EQUIPMENT_STRIDE)
    traits_table = find_table(executable, ("高値Ｌｖ１", "高値Ｌｖ２", "高値Ｌｖ３"), TRAIT_STRIDE)
    synthesis_tables = find_locale_tables(executable, synthesis, SYNTHESIS_STRIDE)
    material_tables = find_locale_tables(executable, materials, MATERIAL_STRIDE)
    equipment_tables = find_locale_tables(executable, equipment, EQUIPMENT_STRIDE)
    trait_tables = find_locale_tables(executable, traits_table, TRAIT_STRIDE)
    map_table = find_table(executable, ("モヨリの森", "ハンデルの森", "ハルト砦"), MAP_STRIDE)
    map_tables = find_map_tables(executable, map_table)
    monster_table = find_table(executable, ("ノーコーン", "ユニコーン", "あばれ黒角獣"), MONSTER_STRIDE)
    monster_tables = find_locale_tables(executable, monster_table, MONSTER_STRIDE)

    category_tables, category_count = _category_tables(executable)
    categories = []
    for category_id in range(category_count):
        names = [record_text(executable, table + category_id * 8) for table in category_tables]
        categories.append({"category_id": category_id, "name_ja": names[0], "name_en": names[1], "name_zh": names[3]})

    items = []
    item_categories = []
    item_qualities = []
    for item_id in range(SYNTHESIS_COUNT):
        offset = synthesis + item_id * SYNTHESIS_STRIDE
        words = _words(executable, offset, SYNTHESIS_STRIDE)
        items.append(
            {
                "game_item_id": item_id,
                "kind": "synthesis",
                **_names(executable, synthesis_tables, item_id, SYNTHESIS_STRIDE),
                "value": words[4],
                "level": words[5],
                "type_code": words[2],
                "source_offset": offset,
            }
        )
        _append_item_categories(item_categories, item_id, words)
        _append_qualities(item_qualities, executable, synthesis_tables, item_id, SYNTHESIS_STRIDE, item_id)

    for index in range(EQUIPMENT_COUNT):
        item_id = SYNTHESIS_COUNT + index
        offset = equipment + index * EQUIPMENT_STRIDE
        words = _words(executable, offset, EQUIPMENT_STRIDE)
        items.append(
            {
                "game_item_id": item_id,
                "kind": "equipment",
                **_names(executable, equipment_tables, index, EQUIPMENT_STRIDE),
                "value": words[4],
                "level": words[5],
                "type_code": words[2],
                "source_offset": offset,
            }
        )
        _append_qualities(item_qualities, executable, equipment_tables, index, EQUIPMENT_STRIDE, item_id, 0x58)

    material_count = 0
    while True:
        name = record_text(executable, materials + material_count * MATERIAL_STRIDE)
        if not name or name.startswith("イベント用予備枠"):
            break
        material_count += 1
    for index in range(material_count):
        item_id = MATERIAL_ITEM_BASE + index
        offset = materials + index * MATERIAL_STRIDE
        words = _words(executable, offset, MATERIAL_STRIDE)
        items.append(
            {
                "game_item_id": item_id,
                "kind": "material",
                **_names(executable, material_tables, index, MATERIAL_STRIDE),
                "value": words[4],
                "level": words[5],
                "type_code": words[2],
                "source_offset": offset,
            }
        )
        _append_item_categories(item_categories, item_id, words)
        _append_qualities(item_qualities, executable, material_tables, index, MATERIAL_STRIDE, item_id)

    recipe_item_ids = {item["game_item_id"] for item in items if item["kind"] == "synthesis"}
    recipe_table = find_recipe_table(executable)
    recipes = []
    recipe_ingredients = []
    for record_index in range(RECIPE_RECORD_COUNT):
        offset = recipe_table + record_index * RECIPE_STRIDE
        words = _words(executable, offset, RECIPE_STRIDE)
        item_id = words[0]
        if item_id not in recipe_item_ids:
            continue
        recipes.append(
            {
                "recipe_id": item_id,
                "item_id": item_id,
                "days": round(struct.unpack_from("<f", executable.data, offset + 8)[0], 2),
                "source_offset": offset,
            }
        )
        for slot, word_index in enumerate((9, 32, 55, 78)):
            reference_id = words[word_index]
            quantity = words[word_index + 1]
            if reference_id == 0xFFFFFFFF or quantity == 0:
                continue
            recipe_ingredients.append(
                {
                    "recipe_id": item_id,
                    "slot": slot,
                    "reference_type": "category" if words[word_index - 1] == 1 else "item",
                    "reference_id": reference_id,
                    "quantity": quantity,
                }
            )

    traits = []
    trait_id = 0
    while True:
        offset = traits_table + trait_id * TRAIT_STRIDE
        name_ja = record_text(executable, offset)
        if not name_ja or name_ja.startswith("予備枠"):
            break
        words = _words(executable, offset, TRAIT_STRIDE)
        descriptions = [clean_description(record_text(executable, table + trait_id * TRAIT_STRIDE, 0x38)) for table in trait_tables]
        traits.append(
            {
                "trait_id": trait_id,
                **_names(executable, trait_tables, trait_id, TRAIT_STRIDE),
                "description_ja": descriptions[0],
                "description_en": descriptions[1],
                "description_zh": descriptions[3],
                "cost": words[3],
                "category_code": words[2],
                "applicability_flags": words[4],
                "source_offset": offset,
            }
        )
        trait_id += 1

    maps = []
    for map_id in range(MAP_COUNT):
        offset = map_table + map_id * MAP_STRIDE
        localized_names = []
        localized_alternate_names = []
        localized_descriptions = []
        localized_alternate_descriptions = []
        for table in map_tables:
            localized_names.append(record_text(executable, table + map_id * MAP_STRIDE))
            localized_alternate_names.append(record_text(executable, table + map_id * MAP_STRIDE, 0x08))
            localized_descriptions.append(clean_description(record_text(executable, table + map_id * MAP_STRIDE, 0x38)))
            localized_alternate_descriptions.append(clean_description(record_text(executable, table + map_id * MAP_STRIDE, 0x40)))
        maps.append(
            {
                "map_id": map_id,
                "name_ja": localized_names[0],
                "name_en": localized_names[1],
                "name_zh": localized_names[3],
                "alternate_name_ja": localized_alternate_names[0],
                "alternate_name_en": localized_alternate_names[1],
                "alternate_name_zh": localized_alternate_names[3],
                "description_ja": localized_descriptions[0],
                "description_en": localized_descriptions[1],
                "description_zh": localized_descriptions[3],
                "alternate_description_ja": localized_alternate_descriptions[0],
                "alternate_description_en": localized_alternate_descriptions[1],
                "alternate_description_zh": localized_alternate_descriptions[3],
                "x": struct.unpack_from("<f", executable.data, offset + 0x20)[0],
                "y": struct.unpack_from("<f", executable.data, offset + 0x24)[0],
                "source_offset": offset,
            }
        )

    monsters = []
    monster_id = 0
    while True:
        name_ja = record_text(executable, monster_table + monster_id * MONSTER_STRIDE)
        if not name_ja or name_ja.startswith("ボス予備枠"):
            break
        offset = monster_table + monster_id * MONSTER_STRIDE
        words = _words(executable, offset, MONSTER_STRIDE)
        monsters.append(
            {
                "monster_id": monster_id,
                **_names(executable, monster_tables, monster_id, MONSTER_STRIDE),
                "level": words[5],
                "source_offset": offset,
            }
        )
        monster_id += 1

    analysis_root = Path(__file__).resolve().parent.parent / "data" / "analysis"
    items_by_field = _collect_associations(analysis_root / "collect-data.bin")
    monsters_by_field = _monster_associations(executable, len(monsters), analysis_root / "meruru-text.bin")
    valid_item_ids = {item["game_item_id"] for item in items}
    map_items = []
    map_monsters = []
    for map_id in range(MAP_COUNT):
        field_ids = _map_field_ids(executable, map_table, map_id)
        item_ids = {item_id for field_id in field_ids for item_id in items_by_field.get(field_id, ())}
        monster_ids = {monster_id for field_id in field_ids for monster_id in monsters_by_field.get(field_id, ())}
        map_items.extend(
            {"map_id": map_id, "item_id": item_id}
            for item_id in sorted(item_ids & valid_item_ids)
        )
        map_monsters.extend(
            {"map_id": map_id, "monster_id": monster_id}
            for monster_id in sorted(monster_ids)
        )

    return {
        "categories": categories,
        "items": items,
        "item_categories": item_categories,
        "item_qualities": item_qualities,
        "recipes": recipes,
        "recipe_ingredients": recipe_ingredients,
        "traits": traits,
        "maps": maps,
        "monsters": monsters,
        "map_items": map_items,
        "map_monsters": map_monsters,
    }
