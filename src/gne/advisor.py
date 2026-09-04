"""向外部顧問要一份填寫建議。

gne 不綁任何一家 AI：要問誰由 `GNE_ADVISOR` 指定，就像 `GIT_EDITOR` 指定編輯器。
gne 只負責把「這個 commit 是什麼」與「欄位該怎麼填」交出去——後者直接送宣告檔的
x-prompt，所以填寫規則仍然只有一份，不會在這裡再抄一遍。

顧問回來的東西一律不被信任：沒宣告的欄位丟掉、人工欄位丟掉、剩下的仍要過宣告檔的
驗證。它從頭到尾只是畫面上的一個建議，收不收由人決定，gne 不會拿它去寫 refs/notes。
"""

import json
import os
import re
import shlex
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .core import git, provenance, schema
from .core.types import NoteDocument

ADVISOR_ENV = "GNE_ADVISOR"
TIMEOUT_SECONDS = 180

# diff 給人看也給顧問看，但不能無上限地塞——超過就截斷並說明截斷了。
DIFF_LIMIT = 60_000

_LINE_RANGE = re.compile(r"\d+(?:-\d+)?")


class AdvisorError(RuntimeError):
    """問不到顧問，或它回來的東西當不成一份建議。"""


class AdvisorNotConfigured(AdvisorError):
    def __init__(self) -> None:
        super().__init__(
            f"沒有設定 {ADVISOR_ENV}，所以沒有可以問的顧問。\n"
            f"它是一行指令：gne 把 commit 與欄位定義用 JSON 從 stdin 餵進去，"
            f"讀 stdout 的 JSON 當建議。"
        )


@dataclass(frozen=True)
class Evidence:
    """建議的依據：這個判斷是看哪一段程式碼得出來的。"""

    path: str
    lines: str
    url: str | None


@dataclass(frozen=True)
class Suggestion:
    note: dict[str, Any]
    reason: str
    evidence: tuple[Evidence, ...]
    ignored: tuple[str, ...]


def command() -> tuple[str, ...]:
    raw = os.environ.get(ADVISOR_ENV, "").strip()
    if not raw:
        raise AdvisorNotConfigured()
    return tuple(shlex.split(raw))


def configured() -> bool:
    return bool(os.environ.get(ADVISOR_ENV, "").strip())


def request_payload(commit: git.CommitInfo, note: NoteDocument) -> str:
    """交出去的東西：commit 的全貌、目前的備註，以及欄位定義本身。"""
    diff = git.commit_diff(commit.branch_hash)
    truncated = len(diff) > DIFF_LIMIT
    return json.dumps(
        {
            "commit": {
                "hash": commit.hash,
                "branch_hash": commit.branch_hash,
                "subject": commit.subject,
                "body": git.commit_body(commit.branch_hash),
                "author": commit.author,
                "date": commit.date,
                "files": git.commit_files(commit.branch_hash),
                "diff": diff[:DIFF_LIMIT],
                "diff_truncated": truncated,
            },
            "note": provenance.fields_of(note),
            "fields": schema.load_schema()["properties"],
        },
        ensure_ascii=False,
    )


def ask(commit: git.CommitInfo, note: NoteDocument) -> Suggestion:
    arguments = command()
    try:
        completed = subprocess.run(
            arguments,
            input=request_payload(commit, note),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except FileNotFoundError as error:
        raise AdvisorError(f"執行不了 {arguments[0]}：{error}") from error
    except subprocess.TimeoutExpired as error:
        raise AdvisorError(f"顧問超過 {TIMEOUT_SECONDS} 秒沒有回應。") from error

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise AdvisorError(f"顧問以 exit {completed.returncode} 結束：{detail[:400]}")

    return parse(completed.stdout, commit.branch_hash)


def parse(payload: str, revision: str) -> Suggestion:
    document = _as_mapping(payload)
    suggested = document.get("suggestion")
    if not isinstance(suggested, Mapping):
        raise AdvisorError("回覆裡沒有 suggestion 這個物件。")

    known = schema.field_by_key()
    note: dict[str, Any] = {}
    ignored: list[str] = []
    for key, value in suggested.items():
        field = known.get(key)
        if field is None or field.human_only:
            ignored.append(key)
            continue
        note[key] = value

    try:
        # 建議也是起點：只建議變更說明而不碰種類是完全合理的一份建議。
        schema.validate_partial(note)
    except schema.NoteValidationError as error:
        raise AdvisorError(f"建議的內容不符合欄位定義：{error}") from error

    return Suggestion(
        note=note,
        reason=str(document.get("reason", "")).strip(),
        evidence=_evidence(document.get("evidence"), revision),
        ignored=tuple(ignored),
    )


def _as_mapping(payload: str) -> Mapping[str, Any]:
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as error:
        raise AdvisorError(f"顧問的輸出不是 JSON：{error}") from error
    if not isinstance(document, Mapping):
        raise AdvisorError(f"顧問的輸出必須是一個物件，讀到 {type(document).__name__}。")
    return document


def _evidence(raw: object, revision: str) -> tuple[Evidence, ...]:
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        return ()
    found: list[Evidence] = []
    for item in raw:
        if not isinstance(item, Mapping) or not item.get("path"):
            continue
        path = str(item["path"])
        lines = str(item.get("lines", "")).strip()
        found.append(Evidence(path=path, lines=lines, url=blob_url(revision, path, lines)))
    return tuple(found)


def blob_url(revision: str, path: str, lines: str = "") -> str | None:
    project = git.remote_web_url()
    if not project:
        return None
    anchor = f"#L{lines}" if _LINE_RANGE.fullmatch(lines) else ""
    return f"{project}/-/blob/{revision}/{path}{anchor}"
