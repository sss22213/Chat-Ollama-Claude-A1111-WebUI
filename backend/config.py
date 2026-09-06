"""集中管理環境設定與預設值。"""
import os
from pathlib import Path

# 本機開發（run.sh）也讀專案根目錄的 .env，行為與 docker compose 一致；
# 已存在的環境變數優先（load_dotenv 預設不覆寫）。
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # 未安裝 python-dotenv 時照常運作（docker 由 compose 注入環境變數）
    pass

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
# 下拉可選的 Claude 模型。可填別名（由 CLI 解析成該系列最新版：
# sonnet→Sonnet 5、opus→Opus 5、fable→Fable 5.1、haiku→Haiku 4.5）或完整 ID
# （claude-opus-4-8、claude-sonnet-4-6 …）；200K 模型可加 "[1m]" 後綴開 1M 視窗。
# 各模型的顯示名稱與 context 見 claude_client.MODEL_CATALOG。
CLAUDE_MODELS = [
    m.strip()
    for m in (os.getenv("CLAUDE_MODELS") or "sonnet,opus,fable,haiku").split(",")
    if m.strip()
]
# context 視窗：0（預設）＝依模型目錄（Fable/Opus 5/Opus 4.7+/Sonnet 5 為 1M，
# Opus 4.6/Sonnet 4.6/Haiku 4.5 為 200K）；設正整數則所有 Claude 模型一律用該值。
CLAUDE_CONTEXT_LENGTH = int(os.getenv("CLAUDE_CONTEXT_LENGTH", "0"))

# ---- OpenAI Codex CLI 引擎 ----
# 後端可選用本地已登入的 `codex`（OpenAI Codex CLI）當 AI 引擎。
# 執行檔在容器內由 compose 掛載 ~/.codex（含 static binary 與 auth.json）；
# 路徑會自動在 CODEX_HOME/packages 下解析，也可用 CODEX_BIN 指定。
CODEX_BIN = os.getenv("CODEX_BIN", "")  # 空字串=自動解析（PATH 或 ~/.codex/packages）
CODEX_TIMEOUT = float(os.getenv("CODEX_TIMEOUT", "300"))
CODEX_EXTRA_ARGS = os.getenv("CODEX_EXTRA_ARGS", "").split()
# 平常會自動讀 ~/.codex/models_cache.json；這裡只是「cache 也讀不到」時的最終後備
# （對應 2026-09 的 codex 模型目錄；空字串視同未設定）。
CODEX_MODELS = [
    m.strip()
    for m in (
        os.getenv("CODEX_MODELS")
        or "gpt-6-astra,gpt-5.6-sol,gpt-5.6-terra,gpt-5.6-luna,gpt-5.5,gpt-5.4-mini"
    ).split(",")
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

# ---- 技能（Agent Skills）外掛 ----
# 放 SKILL.md 外掛的目錄；每個子資料夾＝一個技能（SKILL.md + 選用 references/ scripts/）。
# 相容 Anthropic / Codex 的 Agent Skill 格式，社群 skill 可直接放進來。
SKILLS_DIR = Path(os.getenv("SKILLS_DIR", Path(__file__).parent / "skills"))
# 注入給模型的技能提示詞長度上限（字元）；保護 context 較小的本地模型。
SKILL_MAX_CHARS = int(os.getenv("SKILL_MAX_CHARS", "8000"))

# ---- 伺服器端目錄瀏覽 / 圖片目錄 白名單 ----
# /api/browse、/api/browse/mkdir 與圖片儲存位置只能落在這些根目錄之內
# （冒號分隔，如 PATH）。預設：家目錄與 DATA_DIR。避免後端一旦對外綁定，
# 整台機器的檔案系統被任意瀏覽或寫入。
BROWSE_ROOTS = [
    Path(p).expanduser().resolve()
    for p in os.getenv("BROWSE_ROOTS", f"{Path.home()}:{DATA_DIR}").split(":")
    if p.strip()
]

# CORS 允許來源（Vite dev server）
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5273,http://127.0.0.1:5273,"
    "http://localhost:5173,http://127.0.0.1:5173",
).split(",")
