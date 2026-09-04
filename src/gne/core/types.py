"""gne 的設定與資料型別。"""

from collections.abc import Mapping
from typing import Any, Literal, NotRequired, TypedDict

type Schematic = Literal["json", "yaml"]

# 一份備註。欄位由 note-schema.json 宣告，所以型別上就只能是「鍵到值」——
# 把欄位列成 TypedDict 等於在 Python 裡再抄一份宣告檔，那正是 v2 要拿掉的東西。
type NoteDocument = Mapping[str, Any]

# commit 到它的備註。
type NoteMap = Mapping[str, NoteDocument]


class ControllerOptions(TypedDict):
    schematic: Schematic
    fetch: NotRequired[bool]
    push: NotRequired[bool]
