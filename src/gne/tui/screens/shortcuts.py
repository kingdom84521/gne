"""快捷鍵一覽。

底下那一列只留一顆 `ctrl+h`，其餘的鍵在這裡看。畫面本身不知道有哪些鍵——內容由外面
從真正掛著的 Binding 組好傳進來，所以不會有一份與實際綁定對不上的清單。

按了也做不了事的鍵（例如沒設 `GNE_ADVISOR` 時的「問 AI」）整行顯示成暗的，後面寫上
原因：按下去才發現做不了，不如在清單上就看得出來。
"""

from collections.abc import Sequence

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Label

from ..keys import Section, Shortcut
from .dialog import BOX_CLASS, SCROLL_HINT, Dialog


def row_classes(shortcut: Shortcut) -> str:
    return "info-row unavailable" if shortcut.note else "info-row"


class ShortcutsScreen(Dialog[None]):
    # 再按一次 ctrl+h 就關掉。backspace 一起綁：多數終端機把 ctrl+h 送成同一個位元組。
    BINDINGS = [Binding("escape,ctrl+h,backspace", "close", "關閉")]

    # 焦點放在捲動區上，終端機不夠高的時候上下鍵才看得完。
    AUTO_FOCUS = "#shortcuts-scroll"

    def __init__(self, sections: Sequence[Section]) -> None:
        super().__init__()
        self._sections = tuple(sections)

    def compose(self) -> ComposeResult:
        with Vertical(id="shortcuts", classes=BOX_CLASS):
            yield Label("快捷鍵", classes="dialog-title")
            with VerticalScroll(id="shortcuts-scroll"):
                for section in self._sections:
                    yield Label(section.title, classes="section-title")
                    for shortcut in section.shortcuts:
                        with Horizontal(classes=row_classes(shortcut)):
                            yield Label(shortcut.keys, classes="info-label")
                            yield Label(shortcut.description, classes="info-value")
                            if shortcut.note:
                                yield Label(f"（{shortcut.note}）", classes="shortcut-note")
            yield Label(SCROLL_HINT, classes="dialog-hint")

    def action_close(self) -> None:
        self.dismiss(None)
