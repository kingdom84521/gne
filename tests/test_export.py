import openpyxl
import pytest

from gne import export
from gne.core import schema


def row(commit="a" * 40, subject="feat: 東西", author="Someone", date="2026-01-01", note=None):
    return {"commit": commit, "subject": subject, "author": author, "date": date, "note": note}


def sheet_of(rows, fields=None):
    workbook = export.build_workbook(rows, fields=fields)
    return workbook.active


def test_header_matches_the_existing_xlsx_columns():
    """欄位名沿用舊匯出的英文表頭，只是改由 schema 衍生。"""
    assert [cell.value for cell in sheet_of([])[1]] == [
        "commit hash",
        "commit message",
        "author",
        "date",
        "type",
        "change log",
        "redmine ids",
        "spec change",
        "data migration",
    ]


def test_commit_hash_is_truncated_to_ten_characters():
    assert sheet_of([row()])[2][0].value == "a" * 10


def test_type_uses_the_agreed_short_labels():
    values = [sheet_of([row(note={"type": kind})])[2][4].value for kind in
              ("feat", "fix", "security", "skip")]
    assert values == ["功能", "錯誤", "安全性", "略過"]


def test_redmine_ids_are_newline_joined():
    assert sheet_of([row(note={"type": "fix", "redmine_ids": [1, 2]})])[2][6].value == "1\n2"


def test_a_commit_without_a_note_still_gets_its_metadata_row():
    cells = [cell.value for cell in sheet_of([row()])[2]]
    assert cells[:4] == ["a" * 10, "feat: 東西", "Someone", "2026-01-01"]


def test_an_unknown_type_value_does_not_crash_the_export():
    """舊資料有 type: ''；舊實作在這裡直接 KeyError 炸掉整份 xlsx。"""
    assert sheet_of([row(note={"type": ""})])[2][4].value is not None


def test_a_brand_new_type_value_does_not_crash_the_export():
    assert sheet_of([row(note={"type": "unheard-of"})])[2][4].value == "unheard-of"


def test_a_note_missing_type_does_not_crash_the_export():
    assert sheet_of([row(note={"change_log": "只有說明"})]) is not None


def test_columns_follow_the_schema_so_a_new_field_appears_automatically():
    extended = schema.build_fields(
        {
            "type": "object",
            "required": ["type"],
            "properties": {
                "type": {
                    "title": "變更種類",
                    "type": "string",
                    "enum": ["feat"],
                    "x-input": "choice",
                    "x-choice-labels": {"feat": "功能"},
                    "x-prompt": "怎麼填這個欄位。",
                },
                "reviewed_by": {
                    "title": "審閱者",
                    "type": "string",
                    "x-input": "text",
                    "x-prompt": "誰看過這一筆。",
                },
            },
        }
    )
    header = [cell.value for cell in sheet_of([], fields=extended)[1]]
    assert header[-1] == "reviewed by"


def test_saving_to_an_unwritable_path_reports_clearly(tmp_path):
    target = tmp_path / "missing-directory" / "out.xlsx"
    with pytest.raises(export.ExportError):
        export.write_workbook(export.build_workbook([]), target)


def test_saving_works(tmp_path):
    target = tmp_path / "out.xlsx"
    export.write_workbook(export.build_workbook([row(note={"type": "feat"})]), target)
    assert openpyxl.load_workbook(target).active[2][4].value == "功能"


def test_the_ai_marker_never_reaches_the_spreadsheet():
    """release note 的輸出無視出處記號——它記的是誰寫的，不是變更內容。"""
    note = {"type": "feat", "ai_generated": True}
    sheet = sheet_of([row(note=note)])
    header = [cell.value for cell in sheet[1]]
    assert "ai generated" not in header
    assert all("ai_generated" not in str(cell.value) for cell in sheet[2])
