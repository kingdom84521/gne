# AI 建議

> gne 不綁任何一家 AI：`GNE_ADVISOR` 的契約就是 stdin 進、stdout 出　｜　回到 [readme](../readme.md)

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
