"""狀態與 repository 之間的接縫。

載入與批次寫入都在這裡，state.py 因此可以保持純粹。批次寫入採「逐筆寫本地、
最後推一次」：一個 release 幾十筆備註不該產生幾十次 push。
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ..core import defaults, git, provenance
from ..core.entity import NoteController, NoteError, NoteSyncError
from .state import EditorState


@dataclass(frozen=True)
class SaveOutcome:
    """批次寫入的結果。部分失敗是結果的一種，不是例外。"""

    state: EditorState
    written: tuple[str, ...]
    failures: Mapping[str, str]
    sync_failure: str | None = None

    @property
    def ok(self) -> bool:
        return not self.failures and self.sync_failure is None


def _select(
    commits: Iterable[git.CommitInfo],
    noted: Mapping[str, Mapping[str, object]],
    author_email: str | None,
    unnoted_only: bool,
    ai_only: bool,
) -> list[git.CommitInfo]:
    chosen = list(commits)
    if author_email is not None:
        chosen = [item for item in chosen if item.author_email == author_email]
    if ai_only:
        # 待確認的備註本來就寫進去了，「只看沒填的」在這個模式下沒有意義。
        return [
            item
            for item in chosen
            if item.hash in noted and provenance.is_ai_generated(noted[item.hash])
        ]
    if unnoted_only:
        chosen = [item for item in chosen if item.hash not in noted]
    return chosen


def load(
    controller: NoteController,
    revision_range: str | None = None,
    *,
    author_email: str | None = None,
    unnoted_only: bool = True,
    ai_only: bool = False,
    only: str | None = None,
) -> EditorState:
    """建立初始狀態。指定 only 時只看那一筆，篩選一律不套用。"""
    noted = controller.all_notes()
    if only is not None:
        commits = [git.commit_info(only)]
    else:
        commits = _select(
            git.discover_commits(git.resolve_range(revision_range)),
            noted,
            author_email,
            unnoted_only,
            ai_only,
        )
    return EditorState.of(
        commits,
        saved={item.hash: noted[item.hash] for item in commits if item.hash in noted},
        default=defaults.default_note(),
    )


def save_pending(
    state: EditorState, controller: NoteController, *, push: bool = True
) -> SaveOutcome:
    written: list[str] = []
    failures: dict[str, str] = {}

    for revision, note in state.pending.items():
        try:
            controller.add(note, revision, isForce=True)
        except (NoteError, git.GitError) as error:
            failures[revision] = str(error)
        else:
            written.append(revision)

    sync_failure: str | None = None
    if push and written:
        # 推不出去不代表沒寫進去。丟例外會連「哪幾筆寫成功了」一起丟掉，
        # 而未確認的備註擋著推送時，這是審閱途中的常態。
        try:
            controller.push()
        except (NoteError, NoteSyncError, git.GitError) as error:
            sync_failure = str(error)

    return SaveOutcome(
        state=state.committed(written),
        written=tuple(written),
        failures=failures,
        sync_failure=sync_failure,
    )
