"""把區間內的 commit 與其 note 匯出成 xlsx。

欄位與順序由 note-schema.json 衍生，表頭沿用既有匯出的英文欄名。
"""

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.workbook import Workbook

from .core import schema
from .core.types import NoteDocument

COMMIT_HEADERS = ("commit hash", "commit message", "author", "date")
HASH_LENGTH = 10


class ExportError(RuntimeError):
    pass


def _header_of(field: schema.NoteField) -> str:
    return field.key.replace("_", " ")


def _cell_of(field: schema.NoteField, note: NoteDocument) -> str:
    value = note.get(field.key)
    if schema.is_empty(value):
        return ""
    if field.input == "integer-list":
        return "\n".join(str(item) for item in value)
    if field.input == "choice":
        return field.label_of(str(value))
    return str(value)


def build_workbook(
    rows: Iterable[Mapping[str, Any]],
    fields: Sequence[schema.NoteField] | None = None,
) -> Workbook:
    note_fields = tuple(fields) if fields is not None else schema.note_fields()
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    if sheet is None:
        raise ExportError("openpyxl 沒有建立出工作表。")

    sheet.append([*COMMIT_HEADERS, *(_header_of(field) for field in note_fields)])

    for row in rows:
        line: list[str] = [
            row["commit"][:HASH_LENGTH],
            row.get("subject", ""),
            row.get("author", ""),
            row.get("date", ""),
        ]
        note = row.get("note")
        if note:
            line.extend(_cell_of(field, note) for field in note_fields)
        sheet.append(line)

    return workbook


def write_workbook(workbook: Workbook, target: Path) -> Path:
    try:
        workbook.save(target)
    except OSError as error:
        raise ExportError(f"無法寫入 {target}：{error}") from error
    return target
