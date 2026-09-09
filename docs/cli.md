# 子命令與區間

> 不進畫面就做得到的每一件事，以及「要看哪一段」怎麼決定　｜　回到 [readme](../readme.md)

## 五個入口

| 命令 | 用途 |
| --- | --- |
| `gne [<區間>\|<hash>]` | 開編輯器。`--read-only` 唯讀，看得到但改不了 |
| `gne list [<range>] [--filter all\|noted\|unnoted\|ai-generated] [--format text\|json]` | 用文字列出區間內的 commit 與備註 |
| `gne export [<range>] [-o <path>]` | 匯出 xlsx，預設檔名 `<branch>.xlsx`，不管填到什麼程度 |
| `gne note show [<commit>] [--format text\|yaml\|json]` | 印出單一 commit 的備註 |
| `gne note set [<commit>] --<field> <value>…` | 逐欄寫入，未給的欄位保留原值 |
| `gne note set [<commit>] --from-stdin [--format yaml\|json]` | 從 stdin 覆寫整份備註 |
| `gne note set [<commit>] --ai-generated …` | 同上，但記下這是 AI 填的、待人工確認 |
| `gne note remove [<commit>]` | 刪除備註 |
| `gne note prune [--apply --yes]` | 移除每個欄位都空的備註 |
| `gne note backup [-o <path>]` | 傾印所有帶內容的備註 |
| `gne note push` | 把本機的 refs/notes 推到 remote |
| `gne schema show [--format text\|json]` | 印出欄位宣告 |
| `gne schema init` | 問出這個專案的欄位，寫成 `.gne/note-schema.json` |
| `gne schema order [<key>…]` | 印出或重排欄位的顯示順序 |
| `gne schema add <key> --prompt … [旗標]` | 加一個欄位 |
| `gne schema edit <key> [--rename <new>] [旗標]` | 改一個欄位，沒給的旗標保持原樣 |
| `gne schema remove <key> [--apply --yes]` | 刪一個欄位，預設只說會影響幾筆備註 |

編輯器沒有自己的子命令名字——`gne <區間>` 就是它，因為那是這個工具平常在做的事。
其餘四個各管一件事：`list` 用文字看、`export` 輸出文件、`note` 逐條改備註、`schema` 改欄位宣告。

**`gne note` 與 `gne schema` 是畫面的另一條路**：人在畫面上做得到的每一件事，這裡都有一條
指令做得到，不進畫面、可接管線。給腳本與 AI 走的就是這一條。`gne schema add/edit` 的旗標
與 `Ctrl+F` 的表單收的是同一份東西（見 [欄位宣告](schema.md)），少收一個關鍵字會有測試紅掉。

全域 `--no-push` 讓異動不推送到 remote，批次填寫時建議加上，收尾再 `gne note push` 推一次。

## 區間從哪裡來

同一端可以由三種來源說出來，優先序由高到低：

| | 怎麼給 | 適合 |
| --- | --- | --- |
| 1 | `gne v1.2.0...HEAD` | 這一次就想看這一段 |
| 2 | `--from-file VERSION` / `--to-file …` | release 流程本來就把版本寫在檔案裡 |
| 3 | `GNE_FROM` / `GNE_TO` | 設一次，之後 `gne` 不帶任何東西也會動 |

只講得出起點時終點就是 `HEAD`。三種都沒說話才落到「上一次用過的那一個」——它記在
`.git/gne/range`，是這個 clone 的記憶而不是誰的設定，所以它被蓋掉時不會叫住你。
編輯器裡按 `Ctrl+R` 隨時換；連上一次都沒有時，編輯器會問，不是把你踢回命令列。

**低位階的來源被高位階蓋掉時會先問過你**：

```
$ GNE_FROM=68e56e0 gne list --from-file VERSION
起點用的是 v1.0.0（來自檔案 VERSION）
　被蓋掉的 環境變數 GNE_FROM：68e56e0
要照上面選的值繼續嗎？[y/N]
```

值本身沒錯，錯的是有人以為自己的設定生效了。非互動時不會替你決定——確認過就加 `--yes`。記在 `.git/gne/range`——
它是這個 clone 的暫存狀態，不是專案的宣告，所以不進版控，也不需要誰去忽略它。
沒給、又沒有上一次可以沿用時 gne 會說出來，而不是猜一個你的 repo 裡沒有的 ref。
