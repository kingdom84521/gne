"""新備註的起點。

`.gne/default-note` 是這個 repo 對「一筆備註沒填之前長什麼樣」的宣告，格式與備註本身
一樣是 YAML。與欄位宣告放在同一個目錄底下：兩者都是專案對 gne 說的話。
沒有這個檔就沒有預設值——不是錯誤，只是每一題都從空的開始。

commit 自己說得出來的東西仍然優先：`fix:` 開頭的 commit 預設就是 fix，不會被檔案裡的
值蓋掉。檔案負責的是 commit 說不出來的那部分。
"""

from pathlib import Path
from typing import Any

import yaml

from . import git, provenance, schema
from .types import NoteDocument

DEFAULT_NOTE_RELATIVE = Path(".gne/default-note")


def default_note_path() -> Path:
    return git.repo_root() / DEFAULT_NOTE_RELATIVE


def default_note() -> dict[str, Any]:
    """讀 .gne/default-note。沒有、空的、或不在 repo 裡都回空的。

    內容仍要符合宣告檔：預設值寫錯會在這裡就被擋下來，而不是等到寫入某一筆備註時
    才炸在使用者臉上。
    """
    try:
        raw = default_note_path().read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError, git.GitError):
        return {}

    document = yaml.safe_load(raw) or {}
    if not isinstance(document, dict):
        raise schema.NoteValidationError(
            [f"{DEFAULT_NOTE_RELATIVE} 必須是一組欄位對應，讀到 {type(document).__name__}"]
        )
    fields = provenance.fields_of(document)
    # 部分驗證：預設值是起點，沒有義務把必填欄位填好。
    schema.validate_partial(fields)
    return dict(fields)


def save_default_note(document: dict[str, Any]) -> Path:
    """寫回 .gne/default-note。起點也要符合宣告，錯的預設值不該存進去。"""
    fields = provenance.fields_of(document)
    schema.validate_partial(fields)

    path = default_note_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(dict(fields), allow_unicode=True, sort_keys=False)
    path.write_text(body, encoding="utf-8")
    return path
