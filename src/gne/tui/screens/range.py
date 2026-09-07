"""改看哪一段。

區間以前只能從命令列給：填一輪 release note 的人一天就給一次，改它要先離開工具。
別人的用法不是這樣——今天看這個 tag、明天看那個分支——所以它得是畫面上按得到的東西。
第一次進來沒有可以沿用的區間時，也是這個畫面在問。
"""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Input, Label

from ...core import git
from .dialog import BOX_CLASS, CLOSE_HINT, Dialog

QUESTION = "要看哪一段？"
PLACEHOLDER = "例如 v1.2.0...HEAD"
HINT = f"Enter 套用；{CLOSE_HINT}"

INPUT_ID = "range-input"
ERROR_ID = "range-error"


class RangeScreen(Dialog[str | None]):
    """回傳新的區間；沒改就回 None。"""

    BINDINGS = [Binding("escape", "close", "關閉")]

    def __init__(self, current: str | None = None) -> None:
        super().__init__()
        self._current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="range-box", classes=BOX_CLASS):
            yield Label(QUESTION, id="range-question")
            yield Input(value=self._current or "", placeholder=PLACEHOLDER, id=INPUT_ID)
            yield Label("", id=ERROR_ID, classes="dialog-error")
            yield Label(HINT, classes="dialog-hint")

    def on_mount(self) -> None:
        self.query_one(f"#{INPUT_ID}", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        wanted = event.value.strip()
        if not wanted:
            self._complain("要填一段，例如 v1.2.0...HEAD。")
            return
        if not git.range_is_resolvable(wanted):
            self._complain(f"git 認不得這一段：{wanted}")
            return
        self.dismiss(wanted)

    def _complain(self, message: str) -> None:
        """錯的區間留在原地改，不要關掉讓人從頭打一次。"""
        self.query_one(f"#{ERROR_ID}", Label).update(message)

    def action_close(self) -> None:
        self.dismiss(None)
