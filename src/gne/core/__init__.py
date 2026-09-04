"""gne 的核心：欄位宣告、備註的讀寫、git 存取。

這一層不認識終端機，也不認識命令列——cli 與 tui 都是它的呼叫端，反過來不成立。
界線不靠約定：pyproject.toml 的 import-linter contract 會在越界時失敗。
"""
