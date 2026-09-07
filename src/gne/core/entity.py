"""git notes 的讀寫，以 note-schema.json 為驗證依據。

hash 的把關與 refs/notes 的同步是橫切關注點，宣告在動作方法上面；動作本體因此
只剩一行 git 呼叫。「這個 hash 要不要已經有備註」「這一步要不要推送」看方法上面
那兩行就知道，不必讀完方法體才拼得出來。

驗證關在成對的編解碼裡：控制器手上的 _read 與 _write 兩個方向都驗過，不合宣告檔的
內容因此進不去也出不來。prune 與 backup 必須讀得到不合規的舊資料，那條路走 _raw，
是唯一一個明講不驗證的入口。
"""

import functools
import inspect
import json
from collections.abc import Callable, Mapping
from enum import Enum
from typing import Any

import yaml
from pydantic import TypeAdapter

from . import git, provenance, schema
from .types import ControllerOptions, NoteDocument, NoteMap, Schematic

type NoteReader = Callable[[str, str], dict[str, Any]]
type NoteWriter = Callable[[NoteDocument, str], str]


class ERROR_ID(str, Enum):
    MODEL_NOT_MATCHED = "MODEL_NOT_MATCHED"
    COMMIT_NOT_FOUND = "COMMIT_NOT_FOUND"
    NOTE_NOT_FOUND = "NOTE_NOT_FOUND"
    NOTE_EXISTED = "NOTE_EXISTED"
    REVIEW_PENDING = "REVIEW_PENDING"
    NO_REMOTE = "NO_REMOTE"


_MESSAGES: Mapping[ERROR_ID, str] = {
    ERROR_ID.MODEL_NOT_MATCHED: "備註不符合 note-schema.json 的欄位定義",
    ERROR_ID.COMMIT_NOT_FOUND: "這個 hash 不在目前的 repository 裡",
    ERROR_ID.NOTE_NOT_FOUND: "這個 hash 沒有掛任何備註",
    ERROR_ID.NOTE_EXISTED: "這個 hash 已經有備註了，要覆寫請加上 force",
    ERROR_ID.REVIEW_PENDING: "有備註還沒有人工確認，refs/notes 不能推上 remote",
    ERROR_ID.NO_REMOTE: "這個 repo 沒有 remote，備註只存在本機",
}


class NoteError(Exception):
    def __init__(self, id: ERROR_ID, revision: str | None = None, detail: str | None = None):
        self.id = id
        self.revision = revision
        self.detail = detail
        message = _MESSAGES[id]
        if revision:
            message += f"（commit {revision[:10]}）"
        if detail:
            message += f"：{detail}"
        super().__init__(message)


DIVERGED_NOTICE = (
    "refs/notes 與 origin 分歧了：本機多 {ahead} 筆、origin 多 {behind} 筆。\n"
    "兩邊的備註都在，合併之後才推得上去：git notes merge origin/commits"
)


class NoteSyncError(RuntimeError):
    """與 remote 同步 refs/notes 時失敗。本機的異動已經完成。"""

    def __init__(self, action: str, remote: str, cause: git.GitError):
        self.action = action
        self.remote = remote
        self.cause = cause
        wording = {"fetch": "取回", "push": "推送"}[action]
        super().__init__(f"{wording} {remote} 的 refs/notes 失敗：{cause.stderr.strip()}")


_CODECS: Mapping[Schematic, tuple[Callable[[str], Any], Callable[[Any], str]]] = {
    "json": (json.loads, functools.partial(json.dumps, ensure_ascii=False)),
    "yaml": (yaml.safe_load, functools.partial(yaml.safe_dump, allow_unicode=True)),
}


def _bound(
    action: Callable[..., Any], arguments: tuple[Any, ...], keywords: dict[str, Any]
) -> inspect.BoundArguments:
    """動作的引數，補上預設值。

    inspect.signature 會循著 functools.wraps 設的 __wrapped__ 找回原本的簽章，
    所以 decorator 疊幾層、以什麼順序疊，都讀得到 hash 與 isForce。
    """
    bound = inspect.signature(action).bind(*arguments, **keywords)
    bound.apply_defaults()
    return bound


def _mountpoint(revision: str, *, should_exist: bool, force: bool) -> str:
    """確認這個 hash 動得了，回傳備註真正掛載的完整 sha。"""
    if not git.commit_exists(revision):
        raise NoteError(ERROR_ID.COMMIT_NOT_FOUND, revision)
    resolved = git.resolve_commit(revision)
    noted = resolved in git.notes_list()
    if should_exist and not noted:
        raise NoteError(ERROR_ID.NOTE_NOT_FOUND, resolved)
    if noted and not force:
        raise NoteError(ERROR_ID.NOTE_EXISTED, resolved)
    return resolved


class _NoteDecorator:
    """動作方法的橫切關注點。"""

    @classmethod
    def validate_hash(cls, should_exist: bool = False):
        """把關 hash，並把它換成備註掛載的完整 sha 才交給動作本體。

        動作拿到的一律是掛載位置：cherry-pick 過的 commit 與短 hash 都在這裡收斂完。
        """

        def decorator(action):
            @functools.wraps(action)
            def wrapper(self, *arguments, **keywords):
                bound = _bound(action, (self, *arguments), keywords)
                bound.arguments["hash"] = _mountpoint(
                    bound.arguments["hash"],
                    should_exist=should_exist,
                    force=bool(bound.arguments.get("isForce", should_exist)),
                )
                return action(*bound.args, **bound.kwargs)

            return wrapper

        return decorator

    @classmethod
    def sync_repo(cls, push: bool = False):
        """動作前與 origin 取回一次，動作後視設定推送。

        取回排在把關前面：「這個 hash 有沒有備註」要拿取回後的 refs/notes 回答。
        """

        def decorator(action):
            @functools.wraps(action)
            def wrapper(self, *arguments, **keywords):
                self._fetch_once()
                result = action(self, *arguments, **keywords)
                if push:
                    self._push_if_automatic()
                return result

            return wrapper

        return decorator


class NoteController:
    def __init__(self, options: ControllerOptions):
        TypeAdapter(ControllerOptions).validate_python(options)
        self._loads, self._dumps = _CODECS[options["schematic"]]
        self._read, self._write = self._validating()
        self._fetch_enabled = options.get("fetch", True)
        self._push_enabled = options.get("push", True)
        self._fetched = False
        self._remote_resolved: tuple[str | None] | None = None
        self.sync_notice: str | None = None

    # --- 與 origin 的同步 ---

    def _remote(self) -> str | None:
        """這個 repo 的備註 remote，問一次就記住。"""
        if self._remote_resolved is None:
            self._remote_resolved = (git.notes_remote(),)
        return self._remote_resolved[0]

    def _fetch_once(self) -> None:
        """取回失敗不擋人做事。

        備註是本機先寫、之後才同步的東西。網路不通、VPN 沒開、remote 掛了——這些都
        不影響你把手上這幾筆填完，所以取回失敗是一則說明而不是一個錯誤。真正必須成功
        的是推送，那條路仍然會擋下來。
        """
        if not self._fetch_enabled or self._fetched:
            return
        self._fetched = True

        remote = self._remote()
        if remote is None:
            return

        try:
            git.notes_fetch(remote)
        except git.GitError as error:
            self.sync_notice = str(NoteSyncError("fetch", remote, error))
            return
        self._reconcile()

    def _reconcile(self) -> None:
        """取回之後照 git 的說法報告差異。

        只有本機落後時才把備註快轉過去——那是取回本來的意思。兩邊都有獨有的東西時
        不動它：合併備註可能衝突，那是人要決定的事，不是取回順手做掉的事。
        """
        ahead, behind = git.notes_sync_state()
        if behind and not ahead:
            git.notes_fast_forward()
        elif behind and ahead:
            self.sync_notice = DIVERGED_NOTICE.format(ahead=ahead, behind=behind)

    def take_sync_notice(self) -> str | None:
        """取走同步說明。同一則訊息只該出現一次——畫面上顯示過，離開之後就不該再印。"""
        notice, self.sync_notice = self.sync_notice, None
        return notice

    def push(self) -> None:
        """明確推送一次。批次寫入由呼叫端決定時機，不受逐筆自動推送的設定影響。

        refs/notes 只有一個 ref，推一次就把本機所有備註送上去，所以未確認的備註
        還在時整個推送都不能走。pre-push hook 擋的是同一件事，這裡先擋是為了讓
        工具自己把話講清楚。
        """
        waiting = provenance.unreviewed()
        if waiting:
            raise NoteError(
                ERROR_ID.REVIEW_PENDING,
                detail=f"還有 {len(waiting)} 筆待確認，先用 gne --ai-generated 逐筆看過",
            )
        remote = self._remote()
        if remote is None:
            raise NoteError(ERROR_ID.NO_REMOTE, detail="沒有可以推送的對象")

        try:
            git.notes_push(remote)
        except git.GitError as error:
            raise NoteSyncError("push", remote, error) from error

    def _push_if_automatic(self) -> None:
        """沒有 remote 時「自動推送」沒有對象，不是失敗。明確的 gne push 才會報錯。"""
        if self._push_enabled and self._remote() is not None:
            self.push()

    # --- 欄位異動：宣告改了，既有的備註要跟著改 ---

    def notes_carrying(self, key: str) -> tuple[str, ...]:
        """哪幾筆備註帶著這個欄位。改名或刪除之前要先講得出影響範圍。"""
        return tuple(
            revision for revision, note in self.all_notes().items() if key in note
        )

    def rename_field(self, old_key: str, new_key: str) -> tuple[str, ...]:
        """把既有備註裡的欄位改名，回傳被改寫的那幾筆。

        宣告檔的 additionalProperties 是 false，所以改了宣告卻沒改備註，等於讓所有
        舊備註在下一次讀取時全部驗證失敗。改名是兩件事一起做，不是兩個步驟。
        """
        return self._rewrite(
            lambda note: {new_key if key == old_key else key: value for key, value in note.items()},
            touches=lambda note: old_key in note,
        )

    def drop_field(self, key: str) -> tuple[str, ...]:
        """把欄位從既有備註裡拿掉，回傳被改寫的那幾筆。"""
        return self._rewrite(
            lambda note: {name: value for name, value in note.items() if name != key},
            touches=lambda note: key in note,
        )

    def _rewrite(
        self,
        change: Callable[[dict[str, Any]], dict[str, Any]],
        touches: Callable[[dict[str, Any]], bool],
    ) -> tuple[str, ...]:
        """逐筆改寫備註，不經過驗證。

        改寫進行到一半時，備註對舊宣告與新宣告都不成立——這裡是唯一一個必須繞過
        驗證的地方，所以它不對外開放，只由欄位異動這一條路叫。
        """
        rewritten: list[str] = []
        for revision, note in self.all_notes().items():
            if not touches(note):
                continue
            git.notes_add(revision, self._dumps(change(note)), force=True)
            rewritten.append(revision)

        if rewritten:
            self._push_if_automatic()
        return tuple(rewritten)

    # --- 編解碼：驗證在這裡，繞不過去 ---

    def _validating(self) -> tuple[NoteReader, NoteWriter]:
        """讀與寫共用同一份驗證，兩個方向都關在這一對函式裡。

        寫出去的一律去掉空值再驗；讀回來的驗完才交出去。要跳過驗證只有 _raw 一條路，
        而它的名字就寫著不驗。
        """

        def read(payload: str, revision: str) -> dict[str, Any]:
            return self._checked(self._raw(payload), revision)

        def write(note: NoteDocument, revision: str) -> str:
            return self._dumps(self._checked(schema.strip_empty(note), revision))

        return read, write

    def _raw(self, payload: str) -> dict[str, Any]:
        return self._loads(payload) or {}

    def _checked(self, document: dict[str, Any], revision: str) -> dict[str, Any]:
        """驗證只看宣告過的欄位。gne 自己的記號不在宣告檔裡，先拆下來。"""
        try:
            schema.validate_note(provenance.fields_of(document))
        except schema.NoteValidationError as error:
            raise NoteError(ERROR_ID.MODEL_NOT_MATCHED, revision, str(error)) from error
        return document

    # --- 備註的動作 ---

    @_NoteDecorator.sync_repo(push=True)
    @_NoteDecorator.validate_hash()
    def add(self, note: NoteDocument, hash: str = "HEAD", isForce: bool = False) -> None:
        git.notes_add(hash, self._write(note, hash), force=isForce)

    @_NoteDecorator.sync_repo(push=True)
    @_NoteDecorator.validate_hash(should_exist=True)
    def remove(self, hash: str = "HEAD") -> None:
        git.notes_remove(hash)

    @_NoteDecorator.sync_repo()
    @_NoteDecorator.validate_hash(should_exist=True)
    def show(self, hash: str = "HEAD") -> dict[str, Any]:
        return self._read(git.notes_show(hash), hash)

    @_NoteDecorator.sync_repo()
    @_NoteDecorator.validate_hash(should_exist=True)
    def read_raw(self, hash: str = "HEAD") -> dict[str, Any]:
        """不經驗證讀取：prune 與 backup 必須讀得到不合規的舊資料。"""
        return self._raw(git.notes_show(hash))

    @_NoteDecorator.sync_repo()
    def is_exist(self, hash: str = "HEAD") -> bool:
        """查不到的 hash 不是錯誤——這個方法問的就是存不存在。"""
        return git.commit_exists(hash) and git.resolve_commit(hash) in git.notes_list()

    @_NoteDecorator.sync_repo()
    def all_notes(self) -> dict[str, dict[str, Any]]:
        listing = git.notes_list()
        by_blob = {
            blob: self._raw(git.git_text("cat-file", "-p", blob))
            for blob in set(listing.values())
        }
        return {commit: dict(by_blob[blob]) for commit, blob in listing.items()}
