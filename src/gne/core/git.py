"""執行 git 指令，並提供 commit 與 notes 的查詢。

失敗一律拋 GitError：stdout 與 stderr 分開收，return code 逐次檢查。
輸出會被餵給機器解析，錯誤訊息絕不能混進資料裡。
"""

import re
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

# 上一次用過的區間記在 .git 底下：它是這個 clone 的暫存狀態，不是專案的宣告。
RANGE_CACHE_RELATIVE = Path("gne/range")

# 備註要跟哪個 remote 同步。git config 就是放這種設定的地方，不必自己再開一個檔。
REMOTE_CONFIG_KEY = "gne.remote"
CONVENTIONAL_REMOTE = "origin"

_CHERRY_PICK_PATTERN = re.compile(r"\(cherry picked from commit ([0-9a-f]{7,40})\)")

SHORT_HASH_LENGTH = 10

NOTES_REF = "refs/notes/commits"

# origin 的備註取到這裡。git-notes 文件建議的位置，`git notes merge origin/commits`
# 認得它——就像分支的 refs/remotes/origin/*，本機那一份不會被它蓋掉。
NOTES_TRACKING_REF = "refs/notes/origin/commits"

_FIELD_SEPARATOR = "\x1f"
_LOG_FIELDS = ("%H", "%an", "%ae", "%cd", "%s", "%b")
_LOG_FORMAT = _FIELD_SEPARATOR.join(_LOG_FIELDS)


class RangeNotGiven(RuntimeError):
    """要看哪一段沒人說得出來：這一次沒給，這個 clone 也沒用過任何區間。"""


class RemoteUnclear(RuntimeError):
    """有 remote，但說不出該跟哪一個同步。"""


class GitError(RuntimeError):
    def __init__(self, arguments: tuple[str, ...], returncode: int, stderr: str):
        self.arguments = arguments
        self.returncode = returncode
        self.stderr = stderr
        detail = stderr.strip() or "（沒有錯誤輸出）"
        super().__init__(f"git {' '.join(arguments)} 失敗（exit {returncode}）：{detail}")


def _run(*arguments: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *arguments], capture_output=True, text=True, input=stdin)


def git_raw(*arguments: str, stdin: str | None = None) -> str:
    """未經加工的 stdout。要逐筆解析的輸出走這裡，不能走行導向的 helper。"""
    completed = _run(*arguments, stdin=stdin)
    if completed.returncode != 0:
        raise GitError(arguments, completed.returncode, completed.stderr)
    return completed.stdout


def git_lines(*arguments: str) -> list[str]:
    return git_raw(*arguments).splitlines()


def git_line(*arguments: str) -> str:
    lines = git_lines(*arguments)
    return lines[0] if lines else ""


def git_text(*arguments: str) -> str:
    return "\n".join(git_lines(*arguments))


def git_succeeds(*arguments: str) -> bool:
    return _run(*arguments).returncode == 0


def commit_exists(revision: str) -> bool:
    completed = _run("cat-file", "-t", revision)
    return completed.returncode == 0 and completed.stdout.strip() == "commit"


def resolve_commit(revision: str) -> str:
    return git_line("rev-parse", revision)


def commit_subject(revision: str) -> str:
    return git_line("log", "-1", "--pretty=format:%s", revision)


def commit_author(revision: str) -> str:
    return git_line("log", "-1", "--pretty=format:%an", revision)


def commit_date(revision: str) -> str:
    return git_line("log", "-1", "--pretty=format:%cd", revision)


def commit_body(revision: str) -> str:
    return git_raw("log", "-1", "--pretty=format:%b", revision)


def remote_web_url(remote: str = "origin") -> str | None:
    """origin 對應的網頁位址。組得出來才回傳，組不出來就沒有連結可給。

    GitLab 的 blob 連結長成 <專案>/-/blob/<sha>/<路徑>#L10-20，而 remote 可能是
    https 也可能是 ssh 形式，兩種都要能還原成同一個專案位址。

    remote 裡的帳密一律拔掉：這個 repo 的 origin 就把 access token 嵌在 URL 裡，
    而這裡組出來的連結是要給人看、給人貼的，不能把憑證一起帶出去。
    """
    completed = _run("remote", "get-url", remote)
    if completed.returncode != 0:
        return None
    url = completed.stdout.strip().removesuffix(".git")
    if url.startswith(("http://", "https://")):
        return re.sub(r"^(https?://)[^/@]*@", r"\1", url)
    found = re.fullmatch(r"(?:ssh://)?(?:[^@]+@)?([^:/]+)[:/](.+)", url)
    return f"https://{found.group(1)}/{found.group(2)}" if found else None


def _claimed_origin(body: str) -> str | None:
    found = _CHERRY_PICK_PATTERN.search(body)
    return found.group(1) if found else None


def resolve_existing(candidates: Iterable[str]) -> dict[str, str]:
    """一次問完哪些候選 hash 真的是這個 repository 裡的 commit，回傳完整 hash。

    cherry-pick 標註的來源可能來自這裡沒有的 repository。備註只可能掛在這裡有的
    物件上，所以還原之前必須先確認來源存在。
    """
    wanted = sorted(set(candidates))
    if not wanted:
        return {}
    completed = _run(
        "cat-file", "--batch-check=%(objectname) %(objecttype)", stdin="\n".join(wanted) + "\n"
    )
    if completed.returncode != 0:
        raise GitError(("cat-file", "--batch-check"), completed.returncode, completed.stderr)
    resolved: dict[str, str] = {}
    for candidate, line in zip(wanted, completed.stdout.splitlines()):
        name, _, kind = line.partition(" ")
        if kind == "commit":
            resolved[candidate] = name
    return resolved


def repo_root() -> Path:
    return Path(git_line("rev-parse", "--show-toplevel"))


def git_dir() -> Path:
    return Path(git_line("rev-parse", "--absolute-git-dir"))


def range_cache_path() -> Path:
    """上一次用過的區間記在哪。

    gne 只需要知道一個區間，怎麼給它是呼叫端的事。記住它是為了下一次不必再講一遍。
    放在 .git 底下而不是工作目錄裡：這是某一個 clone 的暫存狀態，不是專案對 gne 的
    宣告，所以不該被 commit，也不該要求誰去忽略它。
    """
    return git_dir() / RANGE_CACHE_RELATIVE


def remembered_range() -> str | None:
    """沒有記錄、空的、或根本不在 repo 裡都回 None。"""
    try:
        recorded = range_cache_path().read_text(encoding="utf-8").strip()
    except (OSError, GitError):
        return None
    return recorded or None


def remember_range(revision_range: str) -> None:
    path = range_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{revision_range}\n", encoding="utf-8")


def resolve_range(given: str | None) -> str:
    """這一次要看的區間：給了就記下來，沒給就沿用上一次。

    沒有可以沿用的就報錯而不是猜一個——猜出來的 ref 在別人的 repo 裡不存在。
    """
    if given:
        if not range_is_resolvable(given):
            raise RangeNotGiven(
                f"git 認不得這一段：{given}\n"
                "區間長成 <起點>...<終點>，兩端都要是這個 repo 裡真的有的 ref。"
            )
        remember_range(given)
        return given

    remembered = remembered_range()
    if remembered:
        return remembered

    raise RangeNotGiven(
        "說不出要看哪一段。給它一個起點，任一種都行：\n"
        "　命令列　gne v1.2.0...HEAD\n"
        "　檔案　　gne --from-file VERSION\n"
        "　環境　　export GNE_FROM=v1.2.0\n"
        "給過一次之後，這個 clone 就會沿用上一次用過的那一個。"
    )


def current_branch() -> str:
    return git_line("branch", "--show-current") or git_line("rev-parse", "--abbrev-ref", "HEAD")


def commits_in_range(revision_range: str) -> list[str]:
    return [item.hash for item in discover_commits(revision_range)]


def notes_grep(pattern: str, ref: str = NOTES_REF) -> list[str]:
    """在整棵 notes tree 裡找符合的備註，回傳被標註的 commit。

    一次 git grep 掃完，不必逐筆 cat-file——1700 筆備註只花毫秒。路徑就是被標註的
    commit，備註多時 git 會把它拆成 fan-out 目錄，去掉斜線才是完整 sha。
    """
    if not git_succeeds("rev-parse", "--verify", "--quiet", ref):
        return []
    arguments = ("grep", "-l", "-e", pattern, ref)
    completed = _run(*arguments)
    if completed.returncode not in (0, 1):
        raise GitError(arguments, completed.returncode, completed.stderr)
    prefix = f"{ref}:"
    return [
        line[len(prefix) :].replace("/", "")
        for line in completed.stdout.splitlines()
        if line.startswith(prefix)
    ]


def notes_list(ref: str = NOTES_REF) -> dict[str, str]:
    if not ref_exists(ref):
        return {}
    entries: dict[str, str] = {}
    for line in git_lines("notes", f"--ref={ref}", "list"):
        blob, _, target = line.partition(" ")
        if target:
            entries[target] = blob
    return entries


def notes_show(revision: str) -> str:
    return git_text("notes", "show", revision)


def notes_add(revision: str, message: str, force: bool) -> None:
    arguments = ["notes", "add"]
    if force:
        arguments.append("-f")
    git_lines(*arguments, "-m", message, revision)


def notes_remove(revision: str) -> None:
    git_lines("notes", "remove", revision)


def remotes() -> tuple[str, ...]:
    return tuple(git_lines("remote"))


def configured_remote() -> str | None:
    completed = _run("config", "--get", REMOTE_CONFIG_KEY)
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def notes_remote() -> str | None:
    """備註跟哪個 remote 同步；沒有 remote 就回 None。

    一個人在自己機器上記備註是完全成立的用法，所以「沒有 remote」是一種狀態而不是
    錯誤。反過來，設了 gne.remote 卻指到不存在的 remote 是設定寫錯，要當場講出來，
    不能安靜地退回本機模式——那會讓人以為推上去了。
    """
    available = remotes()
    configured = configured_remote()

    if configured:
        if configured not in available:
            raise RemoteUnclear(
                f"{REMOTE_CONFIG_KEY} 指的是 {configured}，但這個 repo 沒有這個 remote。"
            )
        return configured

    if CONVENTIONAL_REMOTE in available:
        return CONVENTIONAL_REMOTE

    if len(available) == 1:
        return available[0]

    if available:
        raise RemoteUnclear(
            f"有 {len(available)} 個 remote（{'、'.join(available)}）而且都不叫 "
            f"{CONVENTIONAL_REMOTE}，說不出備註該跟哪一個同步。\n"
            f"用 git config {REMOTE_CONFIG_KEY} <remote> 指定一個。"
        )

    return None


def notes_fetch(remote: str) -> None:
    """把 remote 的備註取到追蹤用的 ref 上。

    不直接取進 refs/notes/commits：那等於 `git fetch origin master:master`，本機只要有
    還沒推的東西就會被拒絕。git 本來的做法是取到 remote-tracking ref，取回永遠成功，
    差異怎麼處理留給你決定。

    --refmap= 不能拿掉：remote.<name>.fetch 可能設著 +refs/notes/*:refs/notes/*，
    而 git 即使收到命令列的 refspec，仍會依設定順手更新對應的 ref（opportunistic update）。
    那條設定帶著 +，於是取回會把本機的 refs/notes/commits 強制退回 origin 那一版，還沒推
    的備註就此消失。空的 --refmap= 關掉那個行為。
    """
    git_lines("fetch", "--refmap=", remote, f"+{NOTES_REF}:{NOTES_TRACKING_REF}")


def range_is_resolvable(revision_range: str) -> bool:
    """git 認不認得這一段。打錯的區間要當場說，不是等掃描到一半才炸。"""
    return git_succeeds("rev-list", "-1", revision_range)


def ref_exists(ref: str) -> bool:
    return git_succeeds("rev-parse", "--verify", "--quiet", ref)


def notes_sync_state() -> tuple[int, int]:
    """(本機獨有幾個, origin 獨有幾個)。就是 git status 那兩個數字。"""
    if not ref_exists(NOTES_TRACKING_REF):
        return (0, 0)
    if not ref_exists(NOTES_REF):
        return (0, int(git_line("rev-list", "--count", NOTES_TRACKING_REF) or 0))
    counted = git_line("rev-list", "--left-right", "--count", f"{NOTES_REF}...{NOTES_TRACKING_REF}")
    ahead, _, behind = counted.partition("\t")
    return (int(ahead or 0), int(behind.strip() or 0))


@dataclass(frozen=True)
class NotesDivergence:
    """本機與 remote 的備註各自有什麼。

    比的是「哪個 commit 掛著哪一個 blob」，不是 commit 圖——兩邊各寫了不同的 commit
    只是各做各的，兩邊對同一個 commit 寫了不一樣的東西才是真的要有人決定。
    """

    only_local: tuple[str, ...] = ()
    only_remote: tuple[str, ...] = ()
    conflicting: tuple[str, ...] = ()

    @property
    def can_unite(self) -> bool:
        """併起來會不會弄丟東西。沒有衝突就是兩邊的聯集，誰都不會少。"""
        return not self.conflicting

    @property
    def needs_uniting(self) -> bool:
        return bool(self.only_remote or self.conflicting)


def notes_divergence() -> NotesDivergence:
    local = notes_list(NOTES_REF)
    tracking = notes_list(NOTES_TRACKING_REF)

    shared = local.keys() & tracking.keys()
    return NotesDivergence(
        only_local=tuple(sorted(local.keys() - tracking.keys())),
        only_remote=tuple(sorted(tracking.keys() - local.keys())),
        conflicting=tuple(sorted(key for key in shared if local[key] != tracking[key])),
    )


def notes_unite() -> None:
    """把 remote 有而本機沒有的備註併進來。

    只在沒有衝突時叫得動——衝突表示同一個 commit 兩邊各寫了不同的東西，合併必須
    挑一邊，那就有東西會不見。挑哪一邊是人的決定，不是這裡順手做掉的事。
    """
    git_lines("notes", "merge", NOTES_TRACKING_REF)


def notes_fast_forward() -> None:
    """本機沒有獨有的東西時，把備註推進到 origin 那一份。取回的意思就是這個。"""
    git_lines("update-ref", NOTES_REF, NOTES_TRACKING_REF)


def notes_push(remote: str) -> None:
    """只推備註本身。refs/notes/* 會連追蹤用的那一份一起推上去。"""
    git_lines("push", remote, f"{NOTES_REF}:{NOTES_REF}")


@dataclass(frozen=True)
class CommitInfo:
    """一筆 commit 在編輯器裡需要的全部資料。

    hash 是備註掛載的位置，cherry-pick 時指向原始來源；branch_hash 是這個分支上的
    commit，看檔案與 diff 要用它——原始 commit 未必存在於本地 repository。
    """

    hash: str
    branch_hash: str
    subject: str
    author: str
    author_email: str
    date: str

    @property
    def short_hash(self) -> str:
        return self.hash[:SHORT_HASH_LENGTH]


def current_user_email() -> str:
    return git_line("config", "user.email")


def _parse_commit_record(record: str) -> tuple[CommitInfo, str | None]:
    """回傳這一筆的資料，以及它宣稱的 cherry-pick 來源（尚未確認存在）。"""
    branch_hash, author, author_email, date, subject, body = record.split(
        _FIELD_SEPARATOR, len(_LOG_FIELDS) - 1
    )
    return (
        CommitInfo(
            hash=branch_hash,
            branch_hash=branch_hash,
            subject=subject,
            author=author,
            author_email=author_email,
            date=date,
        ),
        _claimed_origin(body),
    )


def _with_origins(parsed: Sequence[tuple[CommitInfo, str | None]]) -> list[CommitInfo]:
    resolved = resolve_existing(claimed for _, claimed in parsed if claimed is not None)
    return [
        replace(commit, hash=resolved[claimed])
        if claimed is not None and claimed in resolved
        else commit
        for commit, claimed in parsed
    ]


def discover_commits(revision_range: str) -> list[CommitInfo]:
    """一次 git log 取回區間內的每一筆 commit，cherry-pick 來源在同一趟解開。"""
    raw = git_raw(
        "log",
        revision_range,
        "-z",
        "--right-only",
        "--no-merges",
        f"--pretty=format:{_LOG_FORMAT}",
        "--cherry-pick",
    )
    return _with_origins(
        [_parse_commit_record(record) for record in raw.split("\0") if record.strip()]
    )


def commit_info(revision: str) -> CommitInfo:
    raw = git_raw("log", "-1", "-z", f"--pretty=format:{_LOG_FORMAT}", revision)
    return _with_origins([_parse_commit_record(raw.split("\0")[0])])[0]


def commit_subjects(revisions: Iterable[str]) -> dict[str, str]:
    """一次取回多筆 commit 的標題；不在這個 repository 裡的不會出現在結果中。

    備註可能掛在本地沒有的物件上——refs/notes 是從 origin 取回的，被標註的 commit
    未必跟著來。呼叫端要能區分「查不到」而不是整批失敗。
    """
    present = resolve_existing(revisions)
    if not present:
        return {}
    raw = git_raw(
        "log",
        "--no-walk",
        "--stdin",
        "-z",
        f"--pretty=format:%H{_FIELD_SEPARATOR}%s",
        stdin="\n".join(sorted(set(present.values()))) + "\n",
    )
    subjects: dict[str, str] = {}
    for record in raw.split("\0"):
        if not record.strip():
            continue
        name, _, subject = record.partition(_FIELD_SEPARATOR)
        subjects[name] = subject
    return {
        requested: subjects[full] for requested, full in present.items() if full in subjects
    }


def commit_files(revision: str) -> list[str]:
    return [line for line in git_lines("show", "--pretty=format:", "--name-only", revision) if line]


def commit_diff(revision: str) -> str:
    """用 show 而非 <hash>~1..<hash>，根 commit 沒有前一筆。"""
    return git_text("show", "--pretty=format:", "--patch", revision)


def commit_show(revision: str) -> str:
    """git show 的原樣輸出，含 git 自己上的顏色。

    --color=always 不能省：輸出接的是 subprocess 而不是終端機，git 預設會把顏色關掉。
    畫面上那些顏色因此是 git 依 diff.color 設定給的，不是這裡另外上的一套。
    """
    return git_raw("show", "--color=always", revision)
