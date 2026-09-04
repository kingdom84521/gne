"""把 note 與 commit 列表轉成可讀文字或機器格式。

text 給人看：中文標籤、Redmine 連結。
yaml 是儲存原形，供往返使用。json 忠實對應 note 內容，不補上不存在的欄位。
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import yaml

from .core import provenance, schema
from .core.types import NoteDocument, Schematic

INDENT = "    "

AI_NOTICE = "由 AI 產生，尚未人工確認"


class InputError(ValueError):
    """從 stdin 或檔案讀進來的內容無法當成一份 note。"""


def display_value(field: schema.NoteField, value: Any) -> str:
    """一個欄位值給人看的樣子。識別碼展開成網址、選項換成中文標籤。"""
    if field.input == "integer-list":
        return "\n".join(field.format_item(item) for item in value)
    if field.input == "choice":
        return field.label_of(str(value))
    return str(value)


def note_as_text(document: NoteDocument) -> str:
    known = schema.field_by_key()
    lines: list[str] = [AI_NOTICE] if provenance.is_ai_generated(document) else []

    for field in schema.note_fields():
        value = document.get(field.key)
        if schema.is_empty(value):
            continue
        rendered = display_value(field, value)
        head, *rest = rendered.splitlines() or [""]
        lines.append(f"{field.title}: {head}")
        lines.extend(f"{INDENT}{line}" for line in rest)

    for key, value in document.items():
        if key in known or key in provenance.RESERVED_KEYS or schema.is_empty(value):
            continue
        lines.append(f"{key}: {value}")

    return "\n".join(lines)


def note_as_yaml(document: NoteDocument) -> str:
    return yaml.safe_dump(dict(document), allow_unicode=True, sort_keys=True).rstrip("\n")


def note_as_json(document: NoteDocument) -> str:
    return json.dumps(dict(document), ensure_ascii=False, indent=2)


def parse_note(payload: str, schematic: Schematic) -> dict[str, Any]:
    if not payload.strip():
        raise InputError("輸入是空的，沒有內容可以當成備註。")
    try:
        document = yaml.safe_load(payload) if schematic == "yaml" else json.loads(payload)
    except (yaml.YAMLError, json.JSONDecodeError) as error:
        raise InputError(f"無法解析 {schematic} 內容：{error}") from error
    if not isinstance(document, dict):
        raise InputError(f"備註必須是一組欄位對應，讀到的是 {type(document).__name__}。")
    return document


def rows_as_text(rows: Sequence[Mapping[str, Any]]) -> str:
    blocks: list[str] = []
    for row in rows:
        block = f"{row['commit']}  {row['author']}"
        note = row.get("note")
        if note:
            rendered = note_as_text(note)
            if rendered:
                block += "\n" + "\n".join(f"{INDENT}{line}" for line in rendered.splitlines())
        blocks.append(block)
    return "\n".join(blocks)


def rows_as_json(rows: Iterable[Mapping[str, Any]]) -> str:
    return json.dumps(list(rows), ensure_ascii=False, indent=2)


def _headline(field: schema.NoteField) -> str:
    traits = [field.title, "必填" if field.required else "選填", field.input]
    if field.human_only:
        traits.append("人工填寫")
    if field.ignore_when:
        traits.append(f"{schema.ignore_reason(field)} 時不問")
    return f"{field.key}  （{'，'.join(traits)}）"


def schema_as_text() -> str:
    lines: list[str] = []
    for field in schema.note_fields():
        lines.append(_headline(field))
        for line in field.prompt.splitlines():
            lines.append(f"{INDENT}{line}" if line else "")
        if field.choices:
            for choice in field.choices:
                lines.append(f"{INDENT}- {choice}：{field.label_of(choice)}")
        lines.append(f"{INDENT}CLI 旗標：{field.cli_flag}")
    return "\n".join(lines)
