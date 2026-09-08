"""區間的兩端從哪裡來，以及誰蓋掉誰。"""

import pytest

from gne.core import revisions


def read_nothing(_path: str) -> str | None:
    return None


def test_the_command_line_wins(monkeypatch, tmp_path):
    monkeypatch.setenv(revisions.FROM_ENV, "從環境來的")
    marker = tmp_path / "VERSION"
    marker.write_text("從檔案來的\n")

    resolved = revisions.resolve_end("起點", "從命令列來的", str(marker), revisions.FROM_ENV)

    assert resolved.value == "從命令列來的"
    assert [source.value for source in resolved.shadowed] == ["從檔案來的", "從環境來的"]


def test_the_file_beats_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv(revisions.FROM_ENV, "從環境來的")
    marker = tmp_path / "VERSION"
    marker.write_text("從檔案來的\n")

    resolved = revisions.resolve_end("起點", None, str(marker), revisions.FROM_ENV)

    assert resolved.value == "從檔案來的"
    assert [source.value for source in resolved.shadowed] == ["從環境來的"]


def test_the_environment_alone_is_enough(monkeypatch):
    """這一層就是「直接跑 gne 不帶版本也會動」的那一層。"""
    monkeypatch.setenv(revisions.FROM_ENV, "v1.0.0")
    resolved = revisions.resolve_end("起點", None, None, revisions.FROM_ENV)
    assert resolved.value == "v1.0.0"
    assert resolved.shadowed == ()


def test_nothing_said_anything(monkeypatch):
    monkeypatch.delenv(revisions.FROM_ENV, raising=False)
    resolved = revisions.resolve_end("起點", None, None, revisions.FROM_ENV)
    assert resolved.value is None


def test_a_missing_file_is_not_a_source(monkeypatch, tmp_path):
    """原本那個機制假設檔案在；現在檔案不在就只是這一層沒說話。"""
    monkeypatch.delenv(revisions.FROM_ENV, raising=False)
    resolved = revisions.resolve_end("起點", None, str(tmp_path / "nope"), revisions.FROM_ENV)
    assert resolved.value is None


def test_an_empty_file_is_not_a_source(monkeypatch, tmp_path):
    """fx 那個檔就是 0 bytes——空檔不能算「說了話」。"""
    monkeypatch.delenv(revisions.FROM_ENV, raising=False)
    blank = tmp_path / "VERSION"
    blank.write_text("  \n")
    resolved = revisions.resolve_end("起點", None, str(blank), revisions.FROM_ENV)
    assert resolved.value is None


def test_the_warning_names_who_shadowed_whom(monkeypatch, tmp_path):
    monkeypatch.setenv(revisions.FROM_ENV, "v1.0.0")
    resolved = revisions.resolve_end("起點", "v2.0.0", None, revisions.FROM_ENV)

    warning = revisions.shadowing_warning([resolved])

    assert "v2.0.0" in warning
    assert "v1.0.0" in warning
    assert revisions.FROM_ENV in warning


def test_nothing_shadowed_means_nothing_to_say(monkeypatch):
    monkeypatch.delenv(revisions.FROM_ENV, raising=False)
    resolved = revisions.resolve_end("起點", "v2.0.0", None, revisions.FROM_ENV)
    assert revisions.shadowing_warning([resolved]) == ""


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("a...b", ("a", "b")),
        (" a ... b ", ("a", "b")),
        ("HEAD", None),
        ("a..b", None),
        ("...b", None),
        ("a...", None),
    ],
)
def test_splitting_a_range(text, expected):
    assert revisions.split_range(text) == expected
