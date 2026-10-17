# 範例工作流

`langgraph.json` 照 LangGraph 官方格式：`graphs` 指向 Python 裡的圖，`dependencies` 列出要裝的套件
（`"."` = 這個資料夾；有 `requirements.txt` 會一起裝），`env` 是環境變數檔（只能寫、不能讀回瀏覽器）。

- `illustrate`：想法 → 英文場景 → 標籤 → A1111 生圖 → LLM 看圖檢查，不符合就改標籤重畫（最多 2 張）。
  輸入 `{"idea": "雨夜的書店門口，一隻橘貓在躲雨"}`。
- `chat`：`MessagesState` 聊天圖，用 `webui_app.get_chat_model()`。

在 Python 裡 `import webui_app` 就能用 app 的引擎與工具（不需要 API key）：

| 函式 | 作用 |
|---|---|
| `chat(prompt, *, messages=None, system=None, engine=None, model=None, think=None, images=None, tools=None, skill=None, max_rounds=8, details=False, exclude_tools=None, read_only=False)` | 問 LLM；`images` 可放 `generate_image` 的結果或 `/images/…` 網址讓模型看圖；`tools` 讓模型呼叫工具：`tools="auto"` 把全部的 MCP 工具（生圖、搜尋、技能、A1111 / Civitai Helper 的工具）交給模型自己挑，也可以點名或加上工作流裡的 Python 函式（`["auto", 函式]`）；`read_only=True` 只給查資料的工具、`exclude_tools=[…]` 排除指定工具；`skill="civitai-helper"` 載入技能說明和它的工具 |
| `app_tools(names=None, *, skill=None)` | app / 技能 / MCP 的工具 → LangChain 工具（配 `ToolNode`）；`app_tools("auto")`＝全部 |
| `generate_image(prompt, *, negative_prompt, width, height, seed, steps, cfg_scale, checkpoint)` | A1111 生圖，回 `{"url", "info", "params"}` |
| `list_checkpoints()` | A1111 的 checkpoint 與底模：`{"current", "checkpoints": [{"name", "title", "base"}]}` |
| `web_search(query, max_results=5)` | 網頁搜尋 |
| `ask(title, fields=None, *, message="", images=None)` | 暫停工作流、在工作流頁面請人填表，回 `{欄位: 值}`（範例見 `text2image` 範本） |
| `emit(message)` | 在執行紀錄顯示一行 |
| `get_chat_model()` | LangChain chat model（`llm.invoke(messages)`；`.bind_tools(tools)` 後可接 `ToolNode`） |

每個函式都有 `a` 開頭的 async 版本（`achat`、`agenerate_image`、`alist_checkpoints`、`aweb_search`）。
