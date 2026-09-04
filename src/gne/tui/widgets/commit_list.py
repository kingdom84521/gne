"""左側 commit 列表。

只負責呈現：一列長什麼樣子由純函式決定，狀態由外面餵進來。
每一列固定是「記號 + 短 hash」，寬度因此是常數，左側面板剛好容得下一列而不多佔。
commit 標題由右側承擔——那裡有整行空間，也不必截斷。

瀏覽模式的按鍵掛在這個 widget 上，因此編輯表單取得焦點時它們自動失效——
不會發生打字打到一半觸發「全部寫入」的事。
"""

from collections.abc import Mapping
from typing import Literal

from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from ...core.git import SHORT_HASH_LENGTH, CommitInfo
from .. import keys
from ..state import EditorState

type NoteState = Literal["pending", "ai-generated", "saved", "untouched"]

MARKS: Mapping[NoteState, str] = {
    "pending": "*",
    "ai-generated": "?",
    "saved": "✓",
    "untouched": " ",
}

_ROW_TEMPLATE = "[{mark}] {short_hash}"

# 記號一律是單格字元（✓ 的 East Asian Width 是 Neutral），所以一列的寬度是定值。
ROW_WIDTH = len(_ROW_TEMPLATE.format(mark=MARKS["untouched"], short_hash="x" * SHORT_HASH_LENGTH))


def note_state(state: EditorState, revision: str) -> NoteState:
    """一筆備註的三種處境。列表的記號與資訊對話框的說法都由這裡衍生。"""
    if state.is_edited(revision):
        return "pending"
    if state.is_ai_generated(revision):
        return "ai-generated"
    if state.is_noted(revision):
        return "saved"
    return "untouched"


def mark_for(state: EditorState, revision: str) -> str:
    return MARKS[note_state(state, revision)]


def row_for(state: EditorState, commit: CommitInfo) -> str:
    return _ROW_TEMPLATE.format(mark=mark_for(state, commit.hash), short_hash=commit.short_hash)


class CommitList(OptionList):
    """列表只表達意圖，該怎麼做由 app 決定。"""

    class DetailRequested(Message):
        pass

    class AcceptRequested(Message):
        pass

    class AdviceRequested(Message):
        pass

    class AcceptAllRequested(Message):
        pass

    class SaveRequested(Message):
        pass

    class ReloadRequested(Message):
        pass

    class LeaveRequested(Message):
        pass

    # 每一顆都不上快捷鍵列，改列在 ctrl+h 的清單裡（見 keys.hidden）。
    BINDINGS = [
        keys.hidden("right", "select", "編輯"),
        keys.hidden("i", "request_detail", "檔案與 diff"),
        keys.hidden("a", "request_accept", "用預設填"),
        keys.hidden("question_mark", "request_advice", "AI 建議"),
        # 終端機送的是字面的大寫 A；shift+a 這個鍵名只有支援 Kitty 鍵盤協定的終端機
        # 分得出來。所以綁 A、顯示 shift+a——清單上寫的是使用者要按的東西。
        keys.hidden("A", "request_accept_all", "整批預設", key_display="shift+a"),
        keys.hidden("s", "request_save", "全部寫入"),
        keys.hidden("r", "request_reload", "重新整理"),
        keys.hidden("q", "request_leave", "離開"),
    ]

    def __init__(self, **arguments) -> None:
        super().__init__(**arguments)
        self._state = EditorState()

    @property
    def required_width(self) -> int:
        """一列所需的總寬度，含自身的邊框、內距與捲軸。

        交給 width: auto 的話，讀取中還沒有任何一列時會塌掉、捲軸出現時又會再變一次；
        一次把該留的都算進去，寬度之後就是定值。
        """
        return ROW_WIDTH + self.gutter.width + self.styles.scrollbar_size_vertical

    @property
    def state(self) -> EditorState:
        return self._state

    @property
    def selected_hash(self) -> str | None:
        if self.highlighted is None or not self._state.commits:
            return None
        return self._state.commits[self.highlighted].hash

    def display_state(self, state: EditorState) -> None:
        self._state = state
        self._repaint()

    def action_request_detail(self) -> None:
        self.post_message(self.DetailRequested())

    def action_request_accept(self) -> None:
        self.post_message(self.AcceptRequested())

    def action_request_advice(self) -> None:
        self.post_message(self.AdviceRequested())

    def action_request_accept_all(self) -> None:
        self.post_message(self.AcceptAllRequested())

    def action_request_save(self) -> None:
        self.post_message(self.SaveRequested())

    def action_request_reload(self) -> None:
        self.post_message(self.ReloadRequested())

    def action_request_leave(self) -> None:
        self.post_message(self.LeaveRequested())

    def _repaint(self) -> None:
        previous = self.highlighted
        self.clear_options()
        self.add_options(
            [Option(row_for(self._state, commit), id=commit.hash) for commit in self._state.commits]
        )
        if self._state.commits:
            self.highlighted = min(previous or 0, len(self._state.commits) - 1)
