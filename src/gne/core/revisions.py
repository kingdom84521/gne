"""區間的兩端從哪裡來。

以前的做法是讀一個固定路徑的檔案，讀不到就用寫死的 baseline。那在一個專案裡成立，
換到別人的 repo 就兩件事都不成立：檔案不在那裡，寫死的 ref 也不存在。

現在同一端可以由三種來源說出來，優先序由高到低：

1. **命令列直接給** —— 你這一次講的話最大。
2. **參數指定的檔案** —— 取代原本那個固定路徑：`--from-file` / `--to-file`。
   release 流程通常把版本寫在檔案裡，那就讓它繼續寫在檔案裡，只是路徑由你指定。
3. **環境變數** —— `GNE_FROM` / `GNE_TO`。CI 與 shell 設定檔放這個最省事，
   也是「直接跑 gne 不帶版本也會動」的那一層。

低位階的來源有值、卻被高位階蓋掉時不會安靜地照做：那通常表示有人以為自己設定生效了。
所以這裡把每一端的來源全部收齊回報，要不要繼續由呼叫端問人。
"""

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

FROM_ENV = "GNE_FROM"
TO_ENV = "GNE_TO"

SEPARATOR = "..."


@dataclass(frozen=True)
class Source:
    """一端的一個來源，以及它說了什麼。"""

    name: str
    value: str


@dataclass(frozen=True)
class Resolution:
    """一端最後用哪個值，以及被它蓋掉的那些。"""

    end: str
    """"from" 或 "to"。"""

    chosen: Source | None
    shadowed: tuple[Source, ...] = ()

    @property
    def value(self) -> str | None:
        return None if self.chosen is None else self.chosen.value


def _read(path: str) -> str | None:
    try:
        content = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return content or None


def _sources(
    end: str,
    given: str | None,
    file_path: str | None,
    environment: str,
    read: Callable[[str], str | None],
) -> list[Source]:
    """由高到低排好的來源。沒有值的來源不算來源。"""
    candidates = [
        Source("命令列", given or ""),
        Source(f"檔案 {file_path}", (read(file_path) or "") if file_path else ""),
        Source(f"環境變數 {environment}", os.environ.get(environment, "").strip()),
    ]
    return [source for source in candidates if source.value]


def resolve_end(
    end: str,
    given: str | None,
    file_path: str | None,
    environment: str,
    read: Callable[[str], str | None] = _read,
) -> Resolution:
    found = _sources(end, given, file_path, environment, read)
    if not found:
        return Resolution(end, None)
    return Resolution(end, found[0], tuple(found[1:]))


def split_range(revision_range: str) -> tuple[str, str] | None:
    """`a...b` 拆成兩端。不是這個形狀就回 None，讓呼叫端原樣傳給 git。"""
    before, separator, after = revision_range.partition(SEPARATOR)
    if not separator or not before.strip() or not after.strip():
        return None
    return before.strip(), after.strip()


def compose(first: str, second: str) -> str:
    return f"{first}{SEPARATOR}{second}"


def shadowing_warning(resolutions: Sequence[Resolution]) -> str:
    """被蓋掉的那些說成一段話。沒有被蓋掉的就回空字串。"""
    lines: list[str] = []
    for resolution in resolutions:
        if not resolution.shadowed or resolution.chosen is None:
            continue
        lines.append(f"{resolution.end}用的是 {resolution.chosen.value}（來自{resolution.chosen.name}）")
        lines += [f"　被蓋掉的 {source.name}：{source.value}" for source in resolution.shadowed]
    return "\n".join(lines)
