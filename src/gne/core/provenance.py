"""備註的出處記號：這一份是 AI 產生的，還沒有人看過。

`ai_generated` 刻意不宣告在 note-schema.json 裡——它記的不是 release note 的內容，
而是「這份備註是誰寫的」。輸出 release note 的每一條路徑（純文字、xlsx）都無視它，
只有人工審閱那一條讀它。宣告檔的 additionalProperties 為 false，所以驗證之前必須
先把它拆下來；反過來說，記號名字打錯就會被 jsonschema 當成未宣告的欄位擋下。

記號只回答一個問題：這一筆是不是 AI 寫的。哪幾個欄位由誰填不必記——審閱是逐筆看
整份備註，不是逐欄核對。

記號在人工寫入時消失，不必另外下指令清除：TUI 的表單依欄位重建整份備註，
`gne set` 沒帶 --ai-generated 就是人在寫。審閱過的備註因此與人工填的備註沒有兩樣。
"""

from collections.abc import Iterable
from typing import Any

from . import git, schema
from .types import NoteDocument

AI_GENERATED_KEY = "ai_generated"
RESERVED_KEYS = (AI_GENERATED_KEY,)


def is_ai_generated(document: NoteDocument) -> bool:
    """真值判讀而不是看鍵在不在：`ai_generated: false` 才有辦法表達「不是 AI 寫的」。"""
    return bool(document.get(AI_GENERATED_KEY))


def unreviewed() -> tuple[str, ...]:
    """本機 refs/notes 裡還帶記號的 commit——也就是還沒有人看過的那些。

    記號是備註的頂層鍵，YAML 存出來就是行首的 `ai_generated:`，所以一次 git grep
    就問得完，不必把每一筆備註讀進來。`.githooks/pre-push` 用同一條規則把關，
    那一支是純 bash 的最後防線；兩邊的一致由 tests/test_hooks.py 釘住。
    """
    return tuple(git.notes_grep(f"^{AI_GENERATED_KEY}:"))


def fields_of(document: NoteDocument) -> dict[str, Any]:
    """只留宣告過的欄位那一半。驗證與內容比對都只能看這一半。"""
    return {key: value for key, value in document.items() if key not in RESERVED_KEYS}


def cleared(document: NoteDocument) -> dict[str, Any]:
    """人工確認過的樣子：記號拿掉，欄位一字不動。"""
    return fields_of(document)


def stamped(document: NoteDocument, written: Iterable[str]) -> dict[str, Any]:
    """把這一筆標成 AI 寫的。

    written 是這次寫入設定的欄位，只用來把關人工欄位——記號本身不記它。AI 填不進
    人工欄位是這條路徑的保證，不是靠指示拜託它別填。
    """
    requested = tuple(written)
    _reject_human_only(requested)

    declared = fields_of(document)
    if all(schema.is_empty(declared.get(key)) for key in requested):
        return declared
    return {**declared, AI_GENERATED_KEY: True}


def _reject_human_only(keys: Iterable[str]) -> None:
    known = schema.field_by_key()
    for key in keys:
        field = known.get(key)
        if field is not None and field.human_only:
            raise schema.FieldInputError(
                key, f"{field.title}只能由人工填寫，不能當成 AI 產生的內容寫入。"
            )
