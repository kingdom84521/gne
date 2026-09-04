"""commit 詳情全螢幕畫面：檔案列表與 diff 兩個頁籤。

畫面本身不執行 git——內容由外面查好再傳進來，這一層只負責呈現與捲動。
每個頁籤各自持有捲動容器，切換頁籤因此不會重置捲動位置。
"""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Label, Static, TabbedContent, TabPane

FILES_TAB = "tab-files"
DIFF_TAB = "tab-diff"


class CommitDetailScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape,i", "close", "返回"),
        Binding("tab", "next_tab", "切換頁籤"),
    ]

    def __init__(self, heading: str, files: str, diff: str) -> None:
        super().__init__()
        self._heading = heading
        self._files = files
        self._diff = diff

    def compose(self) -> ComposeResult:
        yield Label(self._heading, id="detail-heading")
        with TabbedContent(id="detail-tabs"):
            with TabPane("檔案列表", id=FILES_TAB):
                yield VerticalScroll(Static(self._files, id="detail-files"))
            with TabPane("Diff", id=DIFF_TAB):
                yield VerticalScroll(Static(self._diff, id="detail-diff"))
        yield Footer()

    def action_close(self) -> None:
        self.dismiss(None)

    def action_next_tab(self) -> None:
        tabs = self.query_one(TabbedContent)
        tabs.active = DIFF_TAB if tabs.active == FILES_TAB else FILES_TAB
