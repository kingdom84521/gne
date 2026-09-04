"""commit 的附帶資訊，以及 `git show` 的原樣輸出。

置頂那條只留 commit 標題——標題可能很長，不該再被 hash 與日期分掉。其餘資訊按鍵
叫出來看：上半是備註掛在哪一筆、狀態如何，下半就是 `git show`——填備註要看的訊息
內文與 diff 都在那裡，不必為了看一眼再換一個畫面。

畫面本身不查 git：內容由外面查好再傳進來，diff 的顏色也是 git 自己上的，這裡不另外
定義一套配色。git show 要跑一下才回得來，先開對話框，回來再填上。
"""

from collections.abc import Sequence

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Label, Static

from .dialog import BOX_CLASS, SCROLL_HINT, Dialog

LOADING = "讀取 commit 內容中…"

SHOW_ID = "commit-info-show"


class CommitInfoScreen(Dialog[None]):
    BINDINGS = [Binding("escape,ctrl+o", "close", "關閉")]

    # 焦點放在捲動區上，上下鍵才捲得動 git show 那一段。
    AUTO_FOCUS = "#commit-info-scroll"

    def __init__(self, rows: Sequence[tuple[str, str]]) -> None:
        super().__init__()
        self._rows = tuple(rows)

    def compose(self) -> ComposeResult:
        with Vertical(id="commit-info", classes=BOX_CLASS):
            yield Label("commit 資訊", classes="dialog-title")
            for label, value in self._rows:
                with Horizontal(classes="info-row"):
                    yield Label(label, classes="info-label")
                    yield Label(value, classes="info-value")
            with VerticalScroll(id="commit-info-scroll"):
                yield Static(LOADING, id=SHOW_ID)
            yield Label(SCROLL_HINT, classes="dialog-hint")

    def show_commit(self, shown: Text) -> None:
        if not self.still_open(f"#{SHOW_ID}"):
            return
        self.query_one(f"#{SHOW_ID}", Static).update(shown)

    def show_problem(self, reason: str) -> None:
        """查不到就把原因原樣說出來，不要留著「讀取中」讓人一直等。"""
        if not self.still_open(f"#{SHOW_ID}"):
            return
        self.query_one(f"#{SHOW_ID}", Static).update(reason)

    def action_close(self) -> None:
        self.dismiss(None)
