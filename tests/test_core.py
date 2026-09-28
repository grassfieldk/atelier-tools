from __future__ import annotations

import struct

from pathlib import Path

from atelier_tools.core import diagnose, find_ebm_layout, pe_sections, read_ebm, search_structured, text_category
from atelier_tools.meruru import extract_structured_data
from atelier_tools.server import create_app


def make_ebm(messages: list[str]) -> bytes:
    output = bytearray(struct.pack("<i", len(messages)))
    for index, message in enumerate(messages):
        encoded = message.encode("utf-8") + b"\0"
        output.extend(struct.pack("<9I", 2, 10, 0, 27, 101, 2, index, 0, len(encoded)))
        output.extend(encoded)
    return bytes(output)


def test_ebm_layout_and_messages(tmp_path):
    path = tmp_path / "sample.ebm"
    path.write_bytes(make_ebm(["姫様、おはようございます。", "フラムを調合した。"]))
    assert find_ebm_layout(path.read_bytes(), 2) == (0, 0)
    records = list(read_ebm(path, "sample.ebm", "JP"))
    assert len(records) == 2
    assert records[0].text == "姫様、おはようございます。"
    assert records[1].category == "event"
    assert records[1].language == "ja"


def test_installed_meruru_is_detected():
    installation = diagnose()
    assert installation.is_valid
    assert installation.japanese_exe
    data = open(installation.japanese_exe, "rb").read()
    sections = pe_sections(data)
    assert any(section["name"] == ".rdata" for section in sections)


def test_meruru_items_recipes_and_traits_are_extracted():
    installation = diagnose()
    structured = extract_structured_data(Path(installation.japanese_exe))
    assert len(structured["items"]) == 344
    assert len(structured["recipes"]) == 180
    assert len(structured["recipe_ingredients"]) == 559
    assert len(structured["traits"]) == 287
    assert len(structured["maps"]) == 45
    assert len(structured["monsters"]) == 89
    assert len(structured["map_items"]) == 468
    assert len(structured["map_monsters"]) == 126
    assert structured["items"][0]["name_zh"] == "卡夫"
    bomb_ingredients = [item for item in structured["recipe_ingredients"] if item["recipe_id"] == 1]
    assert [(item["reference_id"], item["quantity"]) for item in bomb_ingredients] == [(252, 2), (52, 1)]


def test_structured_search_returns_recipe_ingredients():
    recipe = search_structured("recipes", "無限メテオール", "ja", 1)[0]
    assert recipe["days"] == 2.5
    assert [ingredient["name"] for ingredient in recipe["ingredients"]] == ["メテオール", "世界霊魂", "時の石版", "中和剤"]


def test_structured_search_returns_map_contents():
    area = search_structured("maps", "モヨリの森", "ja", 1)[0]
    assert [item["name"] for item in area["items"]] == ["プレイン草", "マジックグラス", "ハチの巣", "千日草", "アイヒェ", "こやし", "にんじん"]
    assert [monster["name"] for monster in area["monsters"]] == ["ノーコーン", "カロッテうさぎ", "青ぷに", "ウォルフ"]


def test_web_api_is_read_only():
    application = create_app()
    api_methods = {
        method
        for route in application.routes
        if route.path.startswith("/api/")
        for method in route.methods
    }
    assert api_methods <= {"GET", "HEAD"}


def test_english_names_are_classified_as_names():
    assert text_category("Alchemist's Robes", "pe") == "name_candidate"
    assert text_category("Bomb", "pe") == "name_candidate"
    assert text_category("FullscreenCamera", "pe") == "identifier"
    assert text_category("string too long", "pe") == "text"
