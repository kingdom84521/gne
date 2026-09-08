# gne — git note editor

在 commit 上掛 release note 用的工具。備註以 YAML 存在 `refs/notes/commits`，要記哪些欄位
由**你的 repo** 說——宣告檔在 `.gne/note-schema.json`，gne 自己不帶預設欄位。

## 兩種用法

```sh
gne schema init         # 問出這個 repo 的欄位（第一次才要）
gne v1.2.0...HEAD       # 開編輯器，列出這個區間裡自己還沒填的 commit
gne                     # 同上，沿用上一次用過的區間
gne list --format json  # 不進畫面，把資料倒出來
```

互動編輯器是入口之一，不是唯一入口——每個操作都有不進畫面就能完成的子命令。

## 編輯器

單一畫面：左側是 commit 列表，右側在預覽與問答之間原地切換，左側不動。編輯先進暫存，
按 `s` 才一次寫入並推送。

填寫是**一問一答**，不是表單：答過的一行一行留在上面，當前的問題永遠在最底下、游標就在那裡，
跟命令列一樣——所以欄位再多也不必捲動。問題、可選值與預設值全部從宣告檔衍生：

```
變更種類: fix（錯誤）
變更說明? （Enter 留空）
▌
```

可選值不是印出來的文字，是一排選得動的東西——`←` `→` 移動、`Enter` 選定，一排最多四個：

```
變更種類? （← → 選，Enter 選定）
 ▐ ▌ feat 功能   ▐●▌ fix 錯誤   ▐ ▌ security 安全性   ▐ ▌ skip 略過
```

游標一開始就落在預設值上（從 commit convention 推出來的那一個），所以「就是它」＝一個 `Enter`。

`Enter` 下一題，問完最後一題自動儲存；`Ctrl+S` 隨時儲存（後面沒答的保留原值）。答錯的那一題
會當場說明並留在原地，你打的東西不會被丟掉。單行輸入框打不出第二行，所以**沒動過的多行舊值
原樣保留**，要寫多行內容走 `gne note set --from-stdin`。

回到問答就能直接打字：對話框關掉、或是點問答那一區的任何地方（問句、答過的那幾行都算），
游標都會回到正在問的那一格，不必再去點準輸入框那一行。

左側每一列固定是「狀態記號 + 短 hash」，面板剛好容得下一列而不多佔。右側置頂只放 commit
標題，用強調色顯示、需要幾行就佔幾行；hash、作者、日期等其餘資訊按 `Ctrl+I` 叫出來。
那個對話框底下接著整份 `git show`：訊息內文與 diff 都在裡面，上下鍵捲動，顏色是 git 自己上的。
填備註要看的東西因此不必再換一個畫面。

`Ctrl+I` 與 `Tab` 在多數終端機是同一個位元組，只有支援 Kitty 鍵盤協定的終端機
（Kitty、WezTerm、Ghostty、foot、較新的 iTerm2 與 Windows Terminal）分得出來。
分不出來的終端機請改按 `Ctrl+O`，兩顆鍵做同一件事。

底下那一列只留 `Ctrl+H`：鍵一多，那一列就從瞄一眼的提示變成要讀的東西。完整清單按 `Ctrl+H`
叫出來，內容從真正掛著的按鍵衍生，不會有一份與實際綁定對不上的清單。多數終端機把 `Ctrl+H`
送成 Backspace 的那個位元組，所以兩顆都認；輸入框自己吃掉 Backspace，打字不受影響。

按了也做不了事的鍵在清單上是暗的，後面寫著原因——沒設 `GNE_ADVISOR` 時的 `?` 就寫「（未設定）」。

離開最順手的是**連按兩次 `Ctrl+C`**：第一次只在快捷鍵列上蓋一條「再按一次 Ctrl+C 不儲存直接
離開」，三秒內沒有第二次就當作沒按過。同一套兩段式也用在 `Esc`——連按兩次清空正在打的那一格，
一次是手滑，兩次才是本意。

會先問的那條路是 `Ctrl+Shift+Q` 而不是 `Ctrl+Q`：後者在 VS Code 上是「結束 VS Code」，按下去會把
編輯器一起關掉。兩顆鍵都綁著同一個動作，因為多數終端機把它們送成同一個位元組。`Ctrl+Shift+W`
（強制關閉，不問）同理只有支援 Kitty 鍵盤協定的終端機分得出來，其餘終端機請用連按兩次 `Ctrl+C`。

編輯中的「取消」綁在 `Ctrl+W` 上，因為 `Esc` 讓給了清空輸入。代價是輸入框裡少了 `Ctrl+W`
原本的「刪掉左邊那個詞」，退格與 `Ctrl+U`（清到行首）都還在。

啟動時要先同步 `refs/notes` 並掃描區間，這段期間左側顯示載入指示器、右側說明正在做什麼，
不會拿空列表冒充「沒有東西」。`Ctrl+Shift+Q` 在任何時候都能離開。

| 模式 | 按鍵 | 作用 |
| --- | --- | --- |
| 瀏覽 | `↑` `↓` | 切換 commit，右側即時顯示 |
| 瀏覽 | `Enter` / `→` | 進入編輯 |
| 瀏覽 | `i` | 開啟 commit 的檔案列表與 diff |
| 瀏覽 | `a` | 用預設內容填這一筆（不進問答）|
| 瀏覽 | `Shift+A` | 把列表上還沒表態的全部用預設內容填起來 |
| 瀏覽 | `?` | 問 AI：建議、理由，以及理由對應的程式碼位置 |
| 瀏覽 | `s` | 把所有暫存的備註寫入並推送一次 |
| 瀏覽 | `r` | 重新掃描 |
| 瀏覽 | `q` | 離開（還有暫存時先問） |
| 編輯 | `Enter` | 答完這一題，問下一題（問完自動儲存這一筆）|
| 編輯 | `←` `→` | 在可選值之間移動（只有選項題有）|
| 編輯 | `Ctrl+S` | 隨時儲存這一筆，回到瀏覽 |
| 編輯 | `Ctrl+W` | 取消，不儲存回到瀏覽（改過了會先問） |
| 編輯 | `Esc` `Esc` | 清空正在打的那一格（連按兩次） |
| 兩者 | `Ctrl+H` | 快捷鍵一覽（下面這張表就是它） |
| 對話框 | `←` `→` `Enter` | 在按鈕之間選、確定（是／否框與 AI 建議框） |
| 兩者 | `Ctrl+I` / `Ctrl+O` | commit 資訊：hash、作者、日期、備註狀態，以及整份 `git show` |
| 兩者 | `F1` | 開啟 commit 的檔案列表與 diff |
| 兩者 | `Ctrl+C` `Ctrl+C` | 不儲存直接離開（連按兩次） |
| 兩者 | `Ctrl+Shift+Q` | 離開（還有暫存時先問） |
| 兩者 | `Ctrl+Shift+W` | 強制關閉（只有分得出這顆鍵的終端機） |

`--read-only` 開起來的編輯器不接受任何會改東西的鍵：鍵還在、`Ctrl+H` 的清單上看得到，
按下去會說是唯讀，而不是沒反應。換區間、看 commit 資訊、看 diff 都還在。
| 兩者 | `Ctrl+R` | 改看哪一段 |
| 兩者 | `Ctrl+D` | 改新備註的起點 |
| 兩者 | `Ctrl+F` | 改欄位宣告 |

列表左側的記號：`[*]` 已編輯待儲存、`[✓]` 已寫入、`[?]` 由 AI 產生待人工確認、`[ ]` 尚未填寫。

九成的備註是「知道有這筆 commit、它不進 release note」，那個值 `.gne/default-note`
與 commit 標題就說得出來，所以 `a` 直接把預設內容填進這一筆、`Shift+A` 一次填整批——這條路不進問答。
填了就是寫入的意思：從「沒有備註」變成「有一筆」是異動，`s` 會把它寫進 refs/notes。

確認框與 commit 資訊都是對話框：背景會壓暗表示此刻點不動，按 `Esc` 或點對話框外面即可關閉。

### 選項

| 選項 | 作用 |
| --- | --- |
| `--author <email>` | 只列出這個人的 commit，預設是自己 |
| `--all-authors` | 列出所有人的 commit |
| `--include-noted` | 連已經有備註的 commit 也列出來 |
| `--range <range>` | 指定 commit 區間 |
| `--ai-generated` | 在上面的篩選之上再收一次：只看 AI 產生、還沒人工確認的那些 |

## 子命令

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

編輯器沒有自己的子命令名字——`gne <區間>` 就是它，因為那是這個工具平常在做的事。
其餘四個各管一件事：`list` 用文字看、`export` 輸出文件、`note` 逐條改備註、`schema` 改欄位宣告。

**`gne note` 底下是編輯器的另一條路**：人在畫面上做得到的每一件事，這裡都有一條指令做得到，
不進畫面、可接管線。給腳本與 AI 走的就是這一條。

全域 `--no-push` 讓異動不推送到 remote，批次填寫時建議加上，收尾再 `gne note push` 推一次。

`<range>` 給過一次就會被記住，之後省略它就是沿用上一次那一個；編輯器裡按 `Ctrl+R` 隨時換。
第一次進來沒有可以沿用的區間時，編輯器會問，不是把你踢回命令列。記在 `.git/gne/range`——
它是這個 clone 的暫存狀態，不是專案的宣告，所以不進版控，也不需要誰去忽略它。
沒給、又沒有上一次可以沿用時 gne 會說出來，而不是猜一個你的 repo 裡沒有的 ref。

## 增修欄位

`Ctrl+F` 在畫面上改，或直接改 `.gne/note-schema.json`（`GNE_SCHEMA` 可以指到別的路徑，
就像 `GNE_ADVISOR` 指定顧問）。兩條路寫的是同一個檔。驗證規則、編輯器表單、`gne note set` 的旗標、
文字與 JSON 輸出、xlsx 表頭都由它衍生，`properties` 的出現順序就是顯示順序。

**改欄位名或刪欄位不只是改宣告。** 宣告的 `additionalProperties` 是 `false`，既有備註裡
那個欄位沒跟著改，下一次讀取就整批驗證失敗。所以畫面上改的時候，gne 會先說有幾筆備註帶著
這個欄位、要一起改寫，答應了才動手——備註先改完，宣告才落地。

改寫的對象必須是完整的那一份，所以動手之前會先跟 remote 併成**兩邊的聯集**：remote 有而
本機沒有的備註先併進來，再一起改。併不起來——同一個 commit 兩邊各寫了不同的東西——就
**拒絕整個異動**，什麼都不動。合併要挑一邊，挑哪一邊是人的決定，不是欄位改名順手做掉的事：

```
本機與 remote 對同一個 commit 各寫了不同的備註：有 2 筆對不起來，
先 git notes merge origin/commits 決定要留哪一份，再改欄位
```

- `x-input`：`text` / `multiline` / `integer-list` / `choice`，決定值怎麼解析（`integer-list` 收逗號分隔的數字，`choice` 把可選值印在問題裡）。
- `x-prompt`：**必填**，這個欄位該怎麼填。人在 `gne schema show` 讀它，顧問收到的 `fields`
  裡也是同一份，填寫規則因此只有一處。沒有它的欄位沒人填得出來，所以宣告時漏了會當場報錯。
- `x-choice-labels`：`choice` 欄位的中文標籤。
- `x-item-url`：`integer-list` 每一項要展開成的網址。
- `x-human-only`：這個欄位只能由人填。AI 寫入時碰到它會被擋下來，不是靠 `x-prompt` 拜託。
- `x-ignore-when`：別的欄位變成什麼值時，這一欄就不必問了。
- `x-follow-convention`：commit 前綴對得上可選值時就用它（只有 `choice` 欄位用得上）。

順序就是 `properties` 的順序，要重排用 `gne schema order`——列出現有的每一個欄位，剛好一次：

```sh
gne schema order                                          # 現在的順序
gne schema order type change_log redmine_ids spec_change  # 排成這樣
```

漏掉的欄位不是「排在後面」而是會消失，所以部分清單會被擋下來。

`Ctrl+F` 的表單收得下上面每一個關鍵字：成對的東西（可選值對標籤、欄位對值）寫成
`feat=功能, fix=錯誤` 與 `type=skip`，一格搞定。所以**畫面上做得到的事不比改檔案少**——
`tests/test_tui_settings.py` 拿隨附的範本逐欄對過去，表單少收一個關鍵字那一條就會紅。

## AI 建議

`?` 會開一個對話框，裡面有三件事：建議的欄位值、為什麼（中文）、以及理由對應的程式碼位置
（`檔案:行數` 加 GitLab blob 連結，點過去看那幾行）。判斷仍然是人的——儲存之後它就是人填的
備註，不帶任何記號；不收就什麼都沒發生。

gne 不綁任何一家 AI。要問誰由 `GNE_ADVISOR` 指定，就像 `GIT_EDITOR` 指定編輯器：

```sh
export GNE_ADVISOR="/path/to/advise.sh"
```

契約很小：**請求 JSON 從 stdin 進去，建議 JSON 從 stdout 出來**。

| 方向 | 內容 |
| --- | --- |
| 請求 | `{"commit": {subject, body, files, diff, …}, "note": {…}, "fields": <宣告檔的 properties>}` |
| 回覆 | `{"suggestion": {<欄位>: <值>}, "reason": "…", "evidence": [{"path": "…", "lines": "10-20"}]}` |

`fields` 直接送宣告檔，所以**填寫規則只有一份**：顧問讀的是每個欄位的 `x-prompt`，不是這支腳本或
gne 裡另抄的一份。回來的東西一律不被信任——沒宣告的欄位、`x-human-only` 的欄位一律丟掉，值還要
過宣告檔的驗證，過不了就顯示原因而不是顯示一份壞建議。`evidence` 的行數由 gne 自己組成連結，
所以顧問不必知道 GitLab 在哪裡；remote 裡嵌的帳密會被拔掉，連結貼出去不會帶著憑證。

顧問就是一支讀 stdin、寫 stdout 的指令，用什麼語言寫、問哪一家模型都可以。換模型或換服務
只要換那一支，gne 這一側不必動。

## AI 產生的備註

AI 代填的備註帶一個 `ai_generated` 欄位：

```yaml
type: fix
change_log: 修正…
ai_generated: true
```

它只回答一個問題：這一筆是不是 AI 寫的。哪幾欄由誰填不記——審閱是逐筆看整份備註，
不是逐欄核對。讀的時候看真值而不是看鍵在不在，所以 `ai_generated: false` 也表達得出
「不是 AI 寫的」。

這個欄位刻意**不在** `note-schema.json` 裡——它記的不是 release note 的內容，而是這份備註
是誰寫的。輸出 release note 的每一條路徑（純文字、xlsx）都無視它，只有審閱那一條讀它。
名字打錯就會被 `additionalProperties: false` 當成未宣告的欄位擋下。

審閱就是把工具打開，只是這次只想看 AI 填的那些——所以它是一個旗標，不是另一套介面：

```sh
gne --ai-generated                       # 我的 commit ∩ AI 填的；儲存這一筆就是確認
gne list --filter ai-generated           # 不進畫面的檢視，可接管線
```

`--ai-generated` 是在既有的作者篩選之上再收一次，所以預設看到的是「自己的」且「AI 填的」；
要看別人的加 `--all-authors`。

人工寫入本身就是確認：TUI 的表單依欄位重建整份備註，`gne note set` 沒帶 `--ai-generated` 就是人在寫，
記號在那一刻消失，不必另外下指令清除。

最後一道防線是 [.githooks/pre-push](.githooks/pre-push)：帶著記號的備註推不上 remote。
要它生效，在被標註的那個 repo 裡把 hook 路徑指過去（`git config core.hooksPath .githooks`）。

## 與 remote 的同步

跟哪個 remote 同步：`git config gne.remote <name>` 指定；沒設就用 `origin`，沒有 `origin`
但只有一個 remote 就用那一個。**一個 remote 都沒有也完全能用**——備註寫在本機，
`gne note push` 會說沒有可以推的對象，其餘一切照常。remote 存在但連不上（VPN 沒開、機器關著）
時取回失敗只是一則說明，不會擋住你把手上這幾筆填完；推送則仍然會失敗，因為那件事真的沒做到。

取回走的是 git 對分支的那一套：remote 的備註取到 `refs/notes/origin/commits`（remote-tracking
ref），本機那一份不會被它蓋掉，所以**本機有還沒推的備註也一樣取得回來**。取回之後：

| 狀態 | gne 做什麼 |
| --- | --- |
| 本機落後 | 直接快轉——取回本來就是這個意思 |
| 本機領先 | 什麼都不做，也不囉嗦 |
| 兩邊都有獨有的 | 不動本機那一份，告訴你兩個數字與 `git notes merge origin/commits` |
| 沒有 remote | 什麼都不做 |
| remote 連不上 | 說一聲，繼續讓你填 |

合併備註可能衝突，那是人要決定的事，不是取回順手做掉的事。

`refs/notes` 是單一個 ref，所以任何一次推送都會把本機所有備註送上 remote，包含還沒確認的那些。
記號跟著備註走，別人 `gne --ai-generated` 一樣看得到，所以這不會弄丟資訊——但要「確認完才公開」就得
在填寫時一路 `--no-push`，等審閱完再 `gne note push`。

## 新備註從哪裡開始

`.gne/default-note` 是 repo 對「一筆備註還沒填之前長什麼樣」的宣告，與欄位宣告放在同一個
目錄底下。`Ctrl+D` 在畫面上改，或直接寫檔——格式與備註本身一樣是 YAML：

```yaml
type: skip
```

commit 標題說得出種類時以標題為準（`fix:` 開頭就是 fix），說不出來時才用這個檔案，
兩者都沒有才落到 `skip`。它是「起點」而不是「一筆備註」，所以不必把必填欄位填滿；
但欄位名與值仍要符合宣告檔，寫錯會在讀取時就被擋下來。

問句會直接說出直接 Enter 會得到什麼：新備註寫「用預設」，已經有備註的寫「保留」。
不想逐題按過去就用 `a`／`A`，那條路不進問答。

## 專案結構

```
gne/
  pyproject.toml        套件宣告、pytest 設定、分層 contract
  src/gne/
    cli.py              命令列入口
    tui/                互動編輯器（Textual）
    render.py           note → 文字 / YAML / JSON
    export.py           note → xlsx
    core/               欄位宣告、備註讀寫、git 存取
      note-schema.json  範例，給人看 x-* 怎麼寫；生效的那一份在被標註的 repo 的 .gne/ 底下
      schema.py  provenance.py  entity.py  git.py  types.py
  tests/
```

界線只有一個方向：上面可以叫下面，下面不能回頭。`core` 不認識 textual、argparse 與
openpyxl，所以換掉介面不必動核心。這條界線是機器在檢查，不是靠資料夾名字提醒——
規則寫在 [pyproject.toml](pyproject.toml) 的 import-linter contract 裡：

```sh
PYTHONPATH=src lint-imports   # 2 kept, 0 broken
```

（`lint-imports` 不讀 pytest 的 `pythonpath`，所以 `src` 要自己給；裝成 editable
（`pip install -e .`）之後可以省。）

新增一個頂層模組而 contract 沒跟著改，`tests/test_packaging.py` 會失敗，不會靜靜地
漏掉那一層。

## 安裝

```sh
./install_dev_env.sh          # 建 .venv，以 editable 模式裝進去
```

裝完在要標註的那個 repo 裡跑一次 `gne schema init`。它不塞一份現成的欄位給你——開一個空的
欄位一覽問你要記什麼，用的是跟 `Ctrl+F` 一樣的表單：

```
  欄位宣告

  這個專案的 release note 要記哪些欄位？按 a 一欄一欄加，加完 ctrl+s
  寫入。
  之後要改，用 gne 裡的 ctrl+f，同一張表單。

  ┌──────────────────────────────────────────────────────────┐
  └──────────────────────────────────────────────────────────┘

  a 新增 ｜ e 修改 ｜ d 刪除 ｜ ctrl+s 儲存；Esc 關閉，或點對話框外面
```

寫出來的 `.gne/note-schema.json` 要 commit——欄位是整個專案共用的約定。
`src/gne/core/note-schema.json` 是一個看得到 `x-*` 怎麼寫的例子，gne 自己不讀它。

相依來自 [pyproject.toml](pyproject.toml)，裝完就有 `gne` 指令。要裝進現成的環境就直接
`pip install -e ".[test]"`。

## 開發

```sh
python3 -m pytest
PYTHONPATH=src lint-imports
```
