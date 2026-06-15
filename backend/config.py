"""集中管理環境設定與預設值。"""
import os
from pathlib import Path

# 服務位址（docker 已對外發佈到主機）
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
A1111_URL = os.getenv("A1111_URL", "http://localhost:7860").rstrip("/")

# 圖片落地目錄
DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).parent / "data"))
IMAGE_DIR = DATA_DIR / "images"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

# 預設聊天模型（前端可覆寫）
DEFAULT_CHAT_MODEL = os.getenv("DEFAULT_CHAT_MODEL", "qwen3.5:35b")

# 預設 SD 生成參數（前端 ImageParamsPanel 可覆寫）
DEFAULT_IMAGE_SETTINGS = {
    "steps": 28,
    "cfg_scale": 5.0,
    "width": 1024,
    "height": 1024,
    "sampler_name": "Euler a",
    "seed": -1,
    # checkpoint 為空字串代表沿用 A1111 當前載入的模型
    "sd_model_checkpoint": "",
    "negative_prompt": "",
    # img2img 重繪力度（0~1）
    "denoising_strength": 0.6,
}

# HTTP 逾時（生成圖片可能很久）
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "600"))

# ---- Claude CLI 引擎 ----
# 後端可選用本地已登入的 `claude`（Claude Code）CLI 當 AI 引擎（與 ollama 二選一）。
CLAUDE_BIN = os.getenv("CLAUDE_BIN", "claude")
# 回覆逾時（秒）
CLAUDE_TIMEOUT = float(os.getenv("CLAUDE_TIMEOUT", "300"))
# 額外傳給 claude 的旗標（空白分隔），需要時可加 --effort low 之類。
CLAUDE_EXTRA_ARGS = os.getenv("CLAUDE_EXTRA_ARGS", "").split()
# 下拉可選的 Claude 模型別名（context window 都是 200k）。
CLAUDE_MODELS = [
    m.strip()
    for m in os.getenv("CLAUDE_MODELS", "sonnet,opus,haiku").split(",")
    if m.strip()
]
CLAUDE_CONTEXT_LENGTH = int(os.getenv("CLAUDE_CONTEXT_LENGTH", "200000"))

# ---- OpenAI Codex CLI 引擎 ----
# 後端可選用本地已登入的 `codex`（OpenAI Codex CLI）當 AI 引擎。
# 執行檔在容器內由 compose 掛載 ~/.codex（含 static binary 與 auth.json）；
# 路徑會自動在 CODEX_HOME/packages 下解析，也可用 CODEX_BIN 指定。
CODEX_BIN = os.getenv("CODEX_BIN", "")  # 空字串=自動解析（PATH 或 ~/.codex/packages）
CODEX_TIMEOUT = float(os.getenv("CODEX_TIMEOUT", "300"))
CODEX_EXTRA_ARGS = os.getenv("CODEX_EXTRA_ARGS", "").split()
# 平常會自動讀 ~/.codex/models_cache.json；這裡只是「cache 也讀不到」時的最終後備。
CODEX_MODELS = [
    m.strip()
    for m in os.getenv("CODEX_MODELS", "gpt-5.5").split(",")
    if m.strip()
]
CODEX_CONTEXT_LENGTH = int(os.getenv("CODEX_CONTEXT_LENGTH", "272000"))
# 沙箱模式：read-only / workspace-write / danger-full-access / bypass
# 容器內若因 landlock 不可用導致沙箱建立失敗，可改成 bypass（容器本身即隔離邊界）。
CODEX_SANDBOX_MODE = os.getenv("CODEX_SANDBOX_MODE", "read-only")

# ---- 提示詞歷史（sd-webui-prompt-history 擴充）----
# 指向該擴充的 data 目錄（含 data.json 與 <id>.jpg）。空字串＝功能停用。
# docker 模式由 compose 固定掛到 /data/prompt-history；本機開發可直接指主機路徑。
PROMPT_HISTORY_DIR = os.getenv("PROMPT_HISTORY_DIR", "").strip()

# CORS 允許來源（Vite dev server）
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5273,http://127.0.0.1:5273,"
    "http://localhost:5173,http://127.0.0.1:5173",
).split(",")
