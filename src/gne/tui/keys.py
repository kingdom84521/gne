"""快捷鍵怎麼寫、哪些上快捷鍵列，以及完整清單怎麼分組。

底下那一列只留一顆 `ctrl+h`：十幾顆鍵擠在同一列，它就從瞄一眼的提示變成要讀的東西，
何況每一顆都得寫成看得懂的形式，那一列還會斷行。完整清單改成按 `ctrl+h` 叫出來。

清單不是另外抄一份：每一條都從真正掛著的 Binding 衍生，鍵或說明改了，對話框跟著改。
只有 Textual 內建、沒有中文說明的那幾顆（↑↓ 移動、Enter 答完這一題）寫成文字。
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from textual.binding import Binding
from textual.keys import format_key


@dataclass(frozen=True)
class Shortcut:
    keys: str
    description: str
    note: str = ""
    """按了也做不了事的原因。有值的那一行會顯示成暗的，並在後面寫上原因。"""


@dataclass(frozen=True)
class Section:
    title: str
    shortcuts: tuple[Shortcut, ...]


def hidden(key: str, action: str, description: str, **extra) -> Binding:
    """掛著，但不上快捷鍵列。除了 ctrl+h 以外的每一顆都走這裡。"""
    return Binding(key, action, description, show=False, **extra)


def spelled_out(binding: Binding) -> str:
    """ctrl+q，不是 ^q。使用者不必先知道脫字符號是什麼意思才按得下去。

    一條綁著好幾顆鍵時全部列出來——除非它自己指定了顯示方式，那通常是因為終端機
    分不出其中幾顆，寫出來只會讓人按錯（見 ctrl+shift+q 與 ctrl+h）。
    """
    if binding.key_display:
        return binding.key_display
    return " / ".join(_spelled_key(key) for key in binding.key.split(","))


def _spelled_key(key: str) -> str:
    *modifiers, last = key.split("+")
    return "+".join([*modifiers, format_key(last)])


def declared(bindings: Iterable[Binding], unavailable: Mapping[str, str]) -> tuple[Shortcut, ...]:
    """unavailable 以 action 名稱指出哪些鍵現在按了也沒用，值就是原因。"""
    return tuple(
        Shortcut(spelled_out(binding), binding.description, unavailable.get(binding.action, ""))
        for binding in bindings
    )


# Textual 內建的移動與選定不是這裡掛的 Binding，也就沒有中文說明可以衍生。
BROWSE_BUILT_IN = (
    Shortcut("↑ ↓", "切換 commit"),
    Shortcut("enter", "進入編輯"),
)

EDIT_BUILT_IN = (
    Shortcut("enter", "答完這一題（選項題是選定游標上的那一個）"),
    Shortcut("← →", "在可選值之間移動（只有選項題有）"),
)


def sections(
    *,
    browse: Iterable[Binding],
    editing: Iterable[Binding],
    anywhere: Iterable[Binding],
    detail: Iterable[Binding],
    unavailable: Mapping[str, str] = {},
) -> tuple[Section, ...]:
    """快捷鍵一覽的內容。分組沿用兩種模式的說法：瀏覽、編輯、兩者都算。

    unavailable 是「這顆鍵現在按了也做不了事」的那幾個 action 與原因——按下去才發現
    做不了，不如在清單上就看得出來。
    """
    return (
        Section("瀏覽", BROWSE_BUILT_IN + declared(browse, unavailable)),
        Section("編輯", EDIT_BUILT_IN + declared(editing, unavailable)),
        Section("兩者", declared(anywhere, unavailable)),
        Section("檔案與 diff 畫面", declared(detail, unavailable)),
    )
