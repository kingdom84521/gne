"""右側置頂的 commit 標題。

標題只佔一行。commit message 想寫多長就寫多長，但右側的版面不該跟著它長高——標題一
撐開，備註預覽與問答就整塊往下擠，而那兩塊才是填備註要看的東西。放不下的字尾換成 …，
右下角用淡色說 `ctrl+o` 看得到完整的 commit 資訊。

沒被截斷時那一行不出現：那時沒有東西被藏起來，一句「還有更多」就成了假話。截斷與否
由字寬對上實際的欄寬算出來，不是猜一個長度上限——視窗變窄變寬都會重算。
"""

from rich.cells import cell_len
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

SUBJECT_ID = "commit-subject"
MORE_ID = "commit-more"
MORE_HINT = "ctrl+o 展開所有資訊"


class CommitHead(Vertical):
    def __init__(self, **arguments) -> None:
        super().__init__(**arguments)
        self._subject = ""

    def compose(self) -> ComposeResult:
        yield Static("", id=SUBJECT_ID)
        yield Static(MORE_HINT, id=MORE_ID)

    def display_subject(self, subject: str) -> None:
        self._subject = subject
        self.query_one(f"#{SUBJECT_ID}", Static).update(subject)
        self._reveal_hint()

    def on_resize(self) -> None:
        """變窄可能把原本放得下的標題截斷，變寬則相反。"""
        self._reveal_hint()

    @property
    def clipped(self) -> bool:
        """這個標題有沒有東西沒顯示出來。

        還沒排版過時欄寬是 0，那時什麼都還沒顯示，也就談不上截斷——排版完會有一次
        Resize 把它算清楚。
        """
        room = self.query_one(f"#{SUBJECT_ID}", Static).content_size.width
        if room <= 0:
            return False
        return cell_len(self._subject) > room or "\n" in self._subject

    def _reveal_hint(self) -> None:
        self.query_one(f"#{MORE_ID}", Static).display = self.clipped
