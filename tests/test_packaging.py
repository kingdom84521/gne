"""包裝宣告是唯一來源。

分層 contract 在這裡對照實際的頂層模組：新增一層而 contract 沒跟上，就不是
「沒管到」而是測試失敗。
"""

import tomllib
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[1]
PACKAGE_DIR = PROJECT_DIR / "src" / "gne"

DUNDER = {"__init__", "__main__", "__pycache__"}


@pytest.fixture(scope="module")
def declaration():
    return tomllib.loads((PROJECT_DIR / "pyproject.toml").read_text(encoding="utf-8"))


def test_the_console_script_points_at_the_cli(declaration):
    assert declaration["project"]["scripts"] == {"gne": "gne.cli:main"}


def test_the_schema_declaration_ships_with_the_package():
    assert (PACKAGE_DIR / "core" / "note-schema.json").is_file()


def layer_names(declaration) -> set[str]:
    contract = next(
        item
        for item in declaration["tool"]["importlinter"]["contracts"]
        if item["type"] == "layers"
    )
    return {
        module.strip().removeprefix("gne.")
        for layer in contract["layers"]
        for module in layer.split("|")
    }


def test_every_top_level_module_is_placed_in_a_layer(declaration):
    present = {
        entry.stem if entry.suffix == ".py" else entry.name
        for entry in PACKAGE_DIR.iterdir()
        if (entry.suffix == ".py" or entry.is_dir())
    } - DUNDER
    assert present == layer_names(declaration)


def test_the_core_layer_is_the_bottom_one(declaration):
    contract = next(
        item
        for item in declaration["tool"]["importlinter"]["contracts"]
        if item["type"] == "layers"
    )
    assert contract["layers"][-1] == "gne.core"
