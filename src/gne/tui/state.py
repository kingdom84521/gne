"""編輯器的狀態代數。

這一層是純的：不執行 git，不匯入 Textual。每次改動都回傳新的 EditorState，
畫面層只負責持有目前那一份。「哪些備註還沒寫進 refs/notes」這條規則因此可以
脫離終端機驗證。
"""

from collections.abc import Iterable
from dataclasses import dataclass, replace
from types import MappingProxyType

from ..core import provenance, schema
from ..core.git import CommitInfo
from ..core.types import NoteDocument, NoteMap


_NO_NOTES: NoteMap = MappingProxyType({})
_NO_NOTE: NoteDocument = MappingProxyType({})


def _freeze_note(note: NoteDocument) -> NoteDocument:
    return MappingProxyType(dict(note))


def _freeze_notes(entries: NoteMap) -> NoteMap:
    return MappingProxyType({key: _freeze_note(value) for key, value in entries.items()})


def seed_for(commit: CommitInfo, default: NoteDocument = _NO_NOTE) -> NoteDocument:
    """新備註的起點：預設值，加上 commit 標題說得出來的東西。

    哪些欄位跟著 commit convention 走是宣告檔說的（x-follow-convention），不是這裡認得
    某個叫 type 的欄位——前綴對得上可選值就用它，對不上才留給預設值。

    預設值由呼叫端讀好傳進來（來源是 .gne/default-note）：這一層不碰檔案也不碰 git。
    """
    base = dict(default)
    prefix = schema.from_convention(commit.subject)
    for field in schema.note_fields():
        if field.follow_convention and prefix in field.choices:
            base[field.key] = prefix
    return _freeze_note(base)


@dataclass(frozen=True)
class EditorState:
    commits: tuple[CommitInfo, ...] = ()
    saved: NoteMap = _NO_NOTES
    pending: NoteMap = _NO_NOTES
    default: NoteDocument = _NO_NOTE
    """還沒填的備註從哪裡開始。來自 .gne/default-note，由 session 讀好交進來。"""

    @staticmethod
    def of(
        commits: Iterable[CommitInfo],
        saved: NoteMap | None = None,
        pending: NoteMap | None = None,
        default: NoteDocument | None = None,
    ) -> "EditorState":
        return EditorState(
            commits=tuple(commits),
            saved=_freeze_notes(saved or {}),
            pending=_freeze_notes(pending or {}),
            default=_freeze_note(default or {}),
        )

    def commit_of(self, revision: str) -> CommitInfo | None:
        return next((item for item in self.commits if item.hash == revision), None)

    def baseline_of(self, revision: str) -> NoteDocument:
        """尚未編輯時該顯示的內容：已存的備註，沒有就是種子。"""
        if revision in self.saved:
            return self.saved[revision]
        commit = self.commit_of(revision)
        return seed_for(commit, self.default) if commit else _NO_NOTE

    def note_of(self, revision: str) -> NoteDocument:
        """要編輯的內容：暫存優先，其次已存的，都沒有就用種子。"""
        return self.pending.get(revision) or self.baseline_of(revision)

    def written_note_of(self, revision: str) -> NoteDocument:
        """真的存在的內容。沒填過就是空的——預覽不能把推測出來的種子講成既有備註。"""
        if revision in self.pending:
            return self.pending[revision]
        return self.saved.get(revision, _NO_NOTE)

    def is_edited(self, revision: str) -> bool:
        return revision in self.pending

    def is_noted(self, revision: str) -> bool:
        return revision in self.saved

    def is_ai_generated(self, revision: str) -> bool:
        """已寫入、但寫的是 AI，還沒有人工確認。暫存中的內容一律出自人手。"""
        return revision in self.saved and provenance.is_ai_generated(self.saved[revision])

    @property
    def pending_count(self) -> int:
        return len(self.pending)

    def staged(self, revision: str, note: NoteDocument) -> "EditorState":
        """存回 refs/notes 裡已經有的那一份就不算改過——否則已編輯標記是騙人的。

        比的是真的存在的內容，不是畫面上的起點：還沒有備註的 commit 用預設內容填，是從
        「沒有備註」變成「有一筆 skip」，那是一次真的異動。九成的備註都是這樣寫進去的，
        拿推測值當原值比，那九成就永遠寫不進去。

        已存的那一份含 AI 記號時同理：欄位一字未改而記號要消失，也是一次真的異動。
        """
        cleaned = schema.strip_empty(note)
        if cleaned == dict(self.saved.get(revision, _NO_NOTE)):
            return self.discarded(revision)
        return replace(self, pending=_freeze_notes({**self.pending, revision: cleaned}))

    def discarded(self, revision: str) -> "EditorState":
        if revision not in self.pending:
            return self
        return replace(
            self,
            pending=_freeze_notes(
                {key: value for key, value in self.pending.items() if key != revision}
            ),
        )

    def committed(self, written: Iterable[str]) -> "EditorState":
        """寫進去的那些從暫存移到已存，寫不進去的原地留著。"""
        done = {revision for revision in written if revision in self.pending}
        return replace(
            self,
            saved=_freeze_notes({**self.saved, **{key: self.pending[key] for key in done}}),
            pending=_freeze_notes(
                {key: value for key, value in self.pending.items() if key not in done}
            ),
        )
