"""執行期可切換、且持久化的應用設定（目前：圖片儲存目錄）。

- image_dir：生成圖片儲存與服務的目錄，可在 UI 中切換。空字串＝預設 DATA_DIR/images。
- known_dirs：歷來用過的「自訂」目錄；切換後舊圖仍能被 /images 服務找到。
設定存於 DATA_DIR/app_settings.json（DATA_DIR 本身固定，不隨 image_dir 變動）。

預設目錄一律以「空字串」存檔、執行期才解析成 DATA_DIR/images：同一份設定檔會被主機上的
開發後端（DATA_DIR=backend/data）與容器（DATA_DIR=/data，綁定到同一個資料夾）共用，
若把某一邊的絕對路徑寫進檔案，另一邊就會往不存在（容器裡則是未掛載、重建即消失）的
路徑存圖。舊版寫進去的絕對路徑在載入時會被正規化回空字串。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from config import (
    DATA_DIR,
    IMAGE_DIR as DEFAULT_IMAGE_DIR,
    OLLAMA_URL,
    A1111_URL,
    A1111_MCP_TOKEN,
    CIVITAI_HELPER_MCP_TOKEN,
    SDCPP_URL,
    SDCPP_MCP_TOKEN,
    MMD_URL,
    MMD_MCP_TOKEN,
    STRATA_URL,
    STRATA_API_KEY,
    PROMPT_HISTORY_DIR as DEFAULT_PROMPT_HISTORY_DIR,
    SKILLS_DIR as DEFAULT_SKILLS_DIR,
    LANGGRAPH_DIR as DEFAULT_LANGGRAPH_DIR,
    SKILL_MAX_CHARS,
)

SETTINGS_FILE = DATA_DIR / "app_settings.json"

# 每個服務來源：mode="api"(直接網址) 或 "docker"(容器名+容器內 port)
def _default_source(url: str, port: int) -> dict:
    return {"mode": "api", "url": url, "container": "", "port": port}


def _default_strata() -> dict:
    # api_key 只存在這個設定檔（後端），get_sources() 不會把它傳給前端
    return {**_default_source(STRATA_URL, 8081), "api_key": STRATA_API_KEY}


def _default_a1111() -> dict:
    # MCP token（A1111 的 /mcp 與 Civitai Helper 的 /civitai-helper/mcp）：跟 api_key 一樣不傳給前端；
    # 空字串＝用環境變數 A1111_MCP_TOKEN / CIVITAI_HELPER_MCP_TOKEN
    return {**_default_source(A1111_URL, 7860), "mcp_token": "", "ch_mcp_token": ""}


def _default_mcp(url: str, port: int) -> dict:
    # 只提供 MCP 伺服器的服務（sd.cpp、MMD 動畫）：網址 + token；空字串＝用環境變數 SDCPP_MCP_TOKEN / MMD_MCP_TOKEN
    return {**_default_source(url, port), "mcp_token": ""}


def _default_sources() -> dict:
    return {
        "ollama": _default_source(OLLAMA_URL, 11434),
        "a1111": _default_a1111(),
        "strata": _default_strata(),
        "sdcpp": _default_mcp(SDCPP_URL, 7861),
        "mmd": _default_mcp(MMD_URL, 5280),
    }


# 來源設定裡的秘密欄位：只存在後端，前端只看得到 <欄位>_set
_SECRET_FIELDS = ("api_key", "mcp_token", "ch_mcp_token")
# MCP 伺服器（mcp_client.SERVERS）→ (服務來源, token 欄位, 環境變數給的 token)
_MCP_TOKENS = {
    "a1111": ("a1111", "mcp_token", A1111_MCP_TOKEN),
    "civitai-helper": ("a1111", "ch_mcp_token", CIVITAI_HELPER_MCP_TOKEN),
    "sdcpp": ("sdcpp", "mcp_token", SDCPP_MCP_TOKEN),
    "mmd": ("mmd", "mcp_token", MMD_MCP_TOKEN),
}
# (服務來源, 秘密欄位) → .env 給的值；服務 → .env 對應的網址（或預設值）
_ENV_SECRETS = {(svc, field): env for svc, field, env in _MCP_TOKENS.values()} | {("strata", "api_key"): STRATA_API_KEY}
_ENV_URLS = {"a1111": A1111_URL, "sdcpp": SDCPP_URL, "mmd": MMD_URL, "strata": STRATA_URL}
# 秘密只送到「可信任網址」（比對 scheme + host + port），每個秘密欄位各自記：
# - trusted[欄位]：設定頁的值只送到這裡＝這個欄位最後一次被輸入非空值時、那次存好的網址；清除就收回
# - .env 的 token 只送到 .env 對應的網址，或 env_trusted[欄位]＝升級時（第一次用新版載入）的已存網址。
#   在設定頁存別的網址、輸入別的欄位，都不會讓 .env 的 token 變成可以送
# 已存網址改到別的 origin、又沒重新輸入的欄位：設定頁的值清掉，記在 secrets_cleared（要重新輸入）


def _default_web() -> dict:
    return {
        "provider": "duckduckgo",  # duckduckgo | searxng
        "searxng_url": "",
        "max_results": 5,
        "fetch_max_chars": 6000,
    }


_settings: dict = {
    "image_dir": "",  # 空字串＝預設 DATA_DIR/images
    "known_dirs": [],
    # 提示詞歷史目錄的 UI 覆寫（空字串＝沿用 env 預設 PROMPT_HISTORY_DIR）
    "prompt_history_dir": "",
    # 技能目錄的 UI 覆寫（空字串＝沿用 env 預設 SKILLS_DIR）；所有 SKILL.md 放這裡
    "skills_dir": "",
    # 允許模型執行技能資料夾內的 Python 腳本（run_skill_script）；預設關閉
    "skill_scripts": False,
    "langgraph_enabled": False,  # 允許執行 LangGraph 工作流（伺服器上跑專案的 Python）
    "langgraph_dir": "",  # 工作流資料夾覆寫；空＝env 預設（LANGGRAPH_DIR）
    # 技能提示詞注入長度上限（字元）；0＝無上限
    "skill_max_chars": SKILL_MAX_CHARS,
    "sources": _default_sources(),
    "web": _default_web(),
}


def _normalize_sources() -> None:
    """確保 sources 結構完整（補齊缺欄位）。"""
    src = _settings.setdefault("sources", {})
    for svc, dflt in _default_sources().items():
        cur = src.get(svc) or {}
        src[svc] = {**dflt, **cur}


def _save() -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(_settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _looks_default(path: str) -> bool:
    """長得像預設目錄（<…>/data/images）的絕對路徑：主機或容器任一邊的預設，一律視為預設。"""
    try:
        q = Path(path)
    except TypeError:
        return False
    return q.name == "images" and q.parent.name == "data"


def _usable(p: Path) -> bool:
    """能建出來且可寫。"""
    try:
        p.mkdir(parents=True, exist_ok=True)
        return os.access(p, os.W_OK)
    except Exception:
        return False


def load() -> dict:
    """啟動時載入；把舊版寫成絕對路徑的預設目錄正規化回空字串，並確保預設目錄存在。"""
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _settings.update(data)
        except Exception:
            pass
    _settings.setdefault("skills_dir", "")
    _settings.setdefault("skill_scripts", False)
    _settings.setdefault("langgraph_enabled", False)
    _settings.setdefault("langgraph_dir", "")
    _settings.setdefault("skill_max_chars", SKILL_MAX_CHARS)
    before = (_settings.get("image_dir"), list(_settings.get("known_dirs") or []))
    img = str(_settings.get("image_dir") or "").strip()
    if _looks_default(img):
        img = ""
    _settings["image_dir"] = img
    _settings["known_dirs"] = [
        d for d in dict.fromkeys(str(x) for x in (_settings.get("known_dirs") or []) if x)
        if not _looks_default(d)
    ]
    _normalize_sources()
    # 升級相容：還沒有可信任網址的服務（舊版設定），目前的已存網址就是各欄位的可信任網址
    # （設定頁的值與 .env 的 token 都是），現有設定不用重新輸入
    trust_added = False
    for svc, src in _settings["sources"].items():
        if svc in _ENV_URLS and "trusted" not in src:
            base = src.pop("trusted_url", None)  # 開發中的舊格式（整個服務一個）
            base = base if isinstance(base, str) and base else effective_url(src)
            fields = [f for f in _SECRET_FIELDS if f in src]
            src["trusted"] = {f: base for f in fields if (src.get(f) or "").strip()}
            src["env_trusted"] = {f: base for f in fields}
            src.setdefault("secrets_cleared", [])
            trust_added = True
    _settings["web"] = {**_default_web(), **(_settings.get("web") or {})}
    DEFAULT_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    if before != (_settings["image_dir"], _settings["known_dirs"]) or (trust_added and SETTINGS_FILE.exists()):
        _save()  # 舊格式改寫回檔案，主機與容器才能共用同一份；可信任網址要在第一次載入時就定下來
    return _settings


def get_image_dir() -> Path:
    """有效的圖片目錄：自訂目錄可用就用它，否則（未設定、建不出來、不可寫）用預設 DATA_DIR/images。"""
    custom = str(_settings.get("image_dir") or "").strip()
    if custom:
        p = Path(custom)
        if _usable(p):
            return p
    DEFAULT_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_IMAGE_DIR


def set_image_dir(path: str) -> Path:
    """切換儲存目錄；會建立目錄並檢查可寫。選到預設目錄就存成空字串。"""
    p = Path(path).expanduser()
    if not p.is_absolute():
        raise ValueError("請提供絕對路徑")
    p.mkdir(parents=True, exist_ok=True)
    if not os.access(p, os.W_OK):
        raise PermissionError("此資料夾無法寫入")
    p = p.resolve()
    p_str = str(p)
    if p == DEFAULT_IMAGE_DIR.resolve() or _looks_default(p_str):
        _settings["image_dir"] = ""
    else:
        _settings["image_dir"] = p_str
        if p_str not in _settings["known_dirs"]:
            _settings["known_dirs"].insert(0, p_str)
    _save()
    return get_image_dir()


def known_image_dirs() -> list[str]:
    """用過的自訂圖片目錄（切換後舊圖仍在那裡）。"""
    return list(_settings.get("known_dirs") or [])


def find_image(filename: str) -> Path | None:
    """在目前、預設與歷來目錄中尋找圖片檔（供 /images 服務，避免切換後舊圖失聯）。"""
    name = Path(filename).name  # 防止路徑穿越
    candidates = [str(get_image_dir()), str(DEFAULT_IMAGE_DIR), *_settings.get("known_dirs", [])]
    seen = set()
    for d in candidates:
        if d in seen:
            continue
        seen.add(d)
        fp = Path(d) / name
        if fp.is_file():
            return fp
    return None


def info() -> dict:
    """目前儲存狀態，給前端顯示。"""
    d = get_image_dir()
    try:
        count = len(list(d.glob("*.png")))
    except Exception:
        count = 0
    return {
        "image_dir": str(d),
        "is_default": not str(_settings.get("image_dir") or "").strip(),
        "default_dir": str(DEFAULT_IMAGE_DIR),
        "writable": os.access(d, os.W_OK),
        "count": count,
        "known_dirs": _settings.get("known_dirs", []),
    }


# ---- 提示詞歷史目錄（env 當預設、UI 可覆寫並持久化）----
def get_prompt_history_dir() -> str:
    """有效歷史目錄：UI 覆寫優先，否則用 env 預設（PROMPT_HISTORY_DIR）。"""
    return (
        (_settings.get("prompt_history_dir") or "").strip()
        or DEFAULT_PROMPT_HISTORY_DIR
    )


def set_prompt_history_dir(path: str) -> dict:
    """設定歷史目錄覆寫；空字串＝清除（回到 env 預設）。

    歷史目錄常是唯讀掛載，故只檢查「存在且為資料夾」，不要求可寫。
    """
    path = (path or "").strip()
    if path:
        p = Path(path).expanduser()
        if not p.is_absolute():
            raise ValueError("請提供絕對路徑")
        if not p.is_dir():
            raise ValueError("找不到此資料夾")
        path = str(p.resolve())
    _settings["prompt_history_dir"] = path
    _save()
    return prompt_history_info()


def prompt_history_info() -> dict:
    """目前歷史目錄狀態（給設定面板顯示）。"""
    effective = get_prompt_history_dir()
    available = bool(
        effective and os.path.isfile(os.path.join(effective, "data.json"))
    )
    return {
        "dir": effective,
        "default": DEFAULT_PROMPT_HISTORY_DIR,
        "override": (_settings.get("prompt_history_dir") or ""),
        "available": available,
    }


# ---- 技能目錄（env 當預設、UI 可覆寫並持久化）----
def get_skills_dir() -> Path:
    """有效技能目錄：UI 覆寫優先，否則用 env 預設（SKILLS_DIR）。skills_store 用它定位。"""
    override = (_settings.get("skills_dir") or "").strip()
    return Path(override) if override else Path(DEFAULT_SKILLS_DIR)


def set_skills_dir(path: str) -> dict:
    """設定技能目錄覆寫；空字串＝清除（回到 env 預設）。會建立目錄並檢查可寫。"""
    path = (path or "").strip()
    if path:
        p = Path(path).expanduser()
        if not p.is_absolute():
            raise ValueError("請提供絕對路徑")
        p.mkdir(parents=True, exist_ok=True)
        if not os.access(p, os.W_OK):
            raise PermissionError("此資料夾無法寫入")
        path = str(p.resolve())
    _settings["skills_dir"] = path
    _save()
    return skills_dir_info()


def skills_dir_info() -> dict:
    """目前技能目錄狀態（給設定面板顯示）。count＝目錄下含 SKILL.md 的子資料夾數。"""
    d = get_skills_dir()
    count = 0
    try:
        if d.is_dir():
            count = sum(
                1 for sub in d.iterdir() if sub.is_dir() and (sub / "SKILL.md").is_file()
            )
    except Exception:
        count = 0
    return {
        "dir": str(d),
        "default": str(DEFAULT_SKILLS_DIR),
        "override": (_settings.get("skills_dir") or ""),
        "writable": os.access(d, os.W_OK) if d.exists() else False,
        "count": count,
        "scripts_enabled": get_skill_scripts(),
        "max_chars": get_skill_max_chars(),
    }


def get_skill_max_chars() -> int:
    """技能提示詞注入長度上限（字元）；0＝無上限。"""
    try:
        return max(0, int(_settings.get("skill_max_chars") or 0))
    except (TypeError, ValueError):
        return 0


def set_skill_max_chars(value: int) -> dict:
    """設定技能提示詞長度上限；0＝無上限，其餘至少 1000 字元（太小會把技能切得不能用）。"""
    v = max(0, int(value or 0))
    if 0 < v < 1000:
        raise ValueError("上限至少 1000 字元，或填 0 表示無上限")
    _settings["skill_max_chars"] = v
    _save()
    return skills_dir_info()


def get_skill_scripts() -> bool:
    """是否允許模型執行技能內的腳本（設定頁開關，持久化）。"""
    return bool(_settings.get("skill_scripts"))


def set_skill_scripts(enabled: bool) -> dict:
    _settings["skill_scripts"] = bool(enabled)
    _save()
    return skills_dir_info()


def get_langgraph_enabled() -> bool:
    """是否允許執行 LangGraph 工作流（工作流頁面的開關，持久化）。"""
    return bool(_settings.get("langgraph_enabled"))


def set_langgraph_enabled(enabled: bool) -> bool:
    _settings["langgraph_enabled"] = bool(enabled)
    _save()
    return get_langgraph_enabled()


def get_langgraph_dir() -> Path:
    """有效的工作流資料夾：UI 覆寫優先，否則用 env 預設（LANGGRAPH_DIR）。"""
    override = (_settings.get("langgraph_dir") or "").strip()
    return Path(override) if override else Path(DEFAULT_LANGGRAPH_DIR)


def set_langgraph_dir(path: str) -> dict:
    """設定工作流資料夾；空字串＝回到預設。會建立資料夾並檢查可寫。"""
    path = (path or "").strip()
    if path:
        p = Path(path).expanduser()
        if not p.is_absolute():
            raise ValueError("請提供絕對路徑")
        p.mkdir(parents=True, exist_ok=True)
        if not os.access(p, os.W_OK):
            raise PermissionError("此資料夾無法寫入")
        path = str(p.resolve())
    _settings["langgraph_dir"] = path
    _save()
    return langgraph_dir_info()


def langgraph_dir_info() -> dict:
    d = get_langgraph_dir()
    return {
        "dir": str(d),
        "default": str(DEFAULT_LANGGRAPH_DIR),
        "override": _settings.get("langgraph_dir") or "",
        "writable": os.access(d, os.W_OK) if d.exists() else os.access(d.parent, os.W_OK),
        # 在 Docker 裡：換的資料夾得是 docker-compose.yml 掛進來的路徑，否則重建容器就不見
        "docker": Path("/.dockerenv").exists(),
    }


# ---- 服務來源（Ollama / A1111 / Strata / sd.cpp / MMD 動畫）----
def effective_url(source: dict) -> str:
    """由來源設定算出實際要連的 URL。"""
    if source.get("mode") == "docker" and source.get("container"):
        return f"http://{source['container']}:{source.get('port')}".rstrip("/")
    return (source.get("url") or "").rstrip("/")


def same_origin(a: str, b: str) -> bool:
    """兩個網址是不是同一個服務：scheme + host + port 都一樣（沒寫 port 用 scheme 的預設值）。
    已存的 API key / MCP token 只送到該服務已儲存的網址，用這個比對。"""
    def key(u: str) -> tuple[str, str, int | None]:
        p = urlsplit((u or "").strip())
        scheme = p.scheme.lower()
        return scheme, (p.hostname or "").lower(), p.port or {"http": 80, "https": 443}.get(scheme)

    try:
        ka, kb = key(a), key(b)
    except ValueError:  # port 不合法
        return False
    return bool(ka[0] and ka[1]) and ka == kb


def get_ollama_url() -> str:
    return effective_url(_settings["sources"]["ollama"])


def get_a1111_url() -> str:
    return effective_url(_settings["sources"]["a1111"])


def get_service_url(service: str) -> str:
    return effective_url(_settings["sources"][service])


def _env_urls(service: str, field: str) -> list[str]:
    """.env 的 token 可以送的網址：.env 對應的網址、升級時記下的網址。"""
    src = _settings["sources"][service]
    return list(dict.fromkeys(u for u in (_ENV_URLS.get(service), (src.get("env_trusted") or {}).get(field)) if u))


def secret_for(service: str, field: str, url: str | None = None) -> str:
    """要送到 url（預設：該服務已存的網址）的秘密；不能送就回空字串。所有用到秘密的地方都經過這裡。
    設定頁填的優先：只在 url 是這個欄位的可信任網址時用。其次 .env 的值：只在 .env 對應的網址或升級時的網址用。"""
    url = get_service_url(service) if url is None else url
    src = _settings["sources"][service]
    saved = (src.get(field) or "").strip()
    if saved and same_origin(url, (src.get("trusted") or {}).get(field) or ""):
        return saved
    env = _ENV_SECRETS.get((service, field)) or ""
    if env and any(same_origin(url, u) for u in _env_urls(service, field)):
        return env
    return ""


def has_secret(service: str, field: str) -> bool:
    """設定頁或 .env 有沒有這個秘密（不管能不能送到目前的網址）。"""
    saved = (_settings["sources"][service].get(field) or "").strip()
    return bool(saved or _ENV_SECRETS.get((service, field)))


def needs_reentry(service: str) -> list[str]:
    """目前的網址拿不到、需要重新輸入的秘密欄位：網址改過而被清掉的，或 .env 有值但不能送到這個網址的。"""
    src = _settings["sources"][service]
    out = []
    for field in _SECRET_FIELDS:
        if field not in src or secret_for(service, field):
            continue
        if field in (src.get("secrets_cleared") or []) or _ENV_SECRETS.get((service, field)):
            out.append(field)
    return out


def get_mcp_token(server: str, url: str | None = None) -> str:
    """MCP 伺服器的 token（要送到 url，預設是已存的網址）。server：a1111 | civitai-helper | sdcpp | mmd。"""
    service, field, _env = _MCP_TOKENS[server]
    return secret_for(service, field, url)


def mcp_token_blocked(server: str) -> bool:
    """這個 MCP 伺服器的 token 因為網址改過而沒送出（要重新輸入）。"""
    service, field, _env = _MCP_TOKENS[server]
    return field in needs_reentry(service)


def get_strata_url() -> str:
    return effective_url(_settings["sources"]["strata"])


def get_strata_key(url: str | None = None) -> str:
    return secret_for("strata", "api_key", url)


def _public(service: str, s: dict) -> dict:
    """給前端的來源設定：API key / MCP token 不外流，只說有沒有設。
    reenter：網址改過、要重新輸入才會送出的秘密欄位（設定頁顯示提示）；
    env_ok_urls：只靠 .env token 的欄位，改到哪些網址 .env 的 token 還會送（設定頁存檔前的提示用）。"""
    out = {k: v for k, v in s.items()
           if k not in _SECRET_FIELDS and k not in ("trusted", "env_trusted", "trusted_url", "secrets_cleared")}
    for key in _SECRET_FIELDS:
        if key in s:
            out[f"{key}_set"] = bool((s.get(key) or "").strip())
    for (svc, field), env in _ENV_SECRETS.items():  # .env 有沒有給（MCP token 與 Strata 的 key 都一樣，只回 true / false）
        if svc == service:
            out[f"{field}_env"] = bool(env)
    if service in _ENV_URLS:
        out["reenter"] = needs_reentry(service)
        out["env_ok_urls"] = {f: _env_urls(service, f) for f in _SECRET_FIELDS
                              if f in s and _ENV_SECRETS.get((service, f))}
    return {**out, "effective_url": effective_url(s)}


def get_sources() -> dict:
    """回傳來源設定 + 算出的有效 URL（給前端顯示）。"""
    return {svc: _public(svc, s) for svc, s in _settings["sources"].items()}


def set_source(service: str, cfg: dict) -> dict:
    """更新某服務來源設定並持久化。"""
    if service not in _settings["sources"]:
        raise ValueError(f"未知服務：{service}")
    cur = _settings["sources"][service]
    mode = cfg.get("mode", cur["mode"])
    if mode not in ("api", "docker"):
        raise ValueError("mode 必須是 api 或 docker")
    updated = {
        "mode": mode,
        "url": (cfg.get("url", cur.get("url")) or "").strip(),
        "container": (cfg.get("container", cur.get("container")) or "").strip(),
        "port": int(cfg.get("port", cur.get("port")) or 0),
    }
    if mode == "api" and not updated["url"]:
        raise ValueError("API 模式需要網址")
    if mode == "docker" and (not updated["container"] or not updated["port"]):
        raise ValueError("Docker 模式需要容器名稱與 port")
    # 網址換到別的 origin：沒有一起重新輸入的欄位不能跟著過去（清掉、記下要重新輸入）
    moved = not same_origin(effective_url(cur), effective_url(updated))
    cleared = list(cur.get("secrets_cleared") or [])
    trusted = dict(cur.get("trusted") or {})
    for field in _SECRET_FIELDS:
        if field not in cur:
            continue
        key = cfg.get(field)
        if key is not None:  # 這次有送：非空＝可信任網址設成這次存好的網址；空字串＝值與可信任網址一起收回
            updated[field] = str(key).strip()
            cleared = [f for f in cleared if f != field]
            if updated[field]:
                trusted[field] = effective_url(updated)
            else:
                trusted.pop(field, None)
        elif moved:
            if (cur.get(field) or "").strip():
                cleared.append(field)
            updated[field] = ""
            trusted.pop(field, None)
        else:  # 沒送＝保持原值
            updated[field] = cur.get(field, "")
    if service in _ENV_URLS:
        updated["trusted"] = trusted
        updated["env_trusted"] = dict(cur.get("env_trusted") or {})  # 升級時的網址：之後不會變
        updated["secrets_cleared"] = sorted(set(cleared))
    _settings["sources"][service] = updated
    _save()
    return _public(service, updated)


# ---- 前端 UI 設定（語言、引擎、SD 參數、system prompt 等）----
# 後端只當不透明的 JSON blob 保存，schema 由前端定義；用於跨裝置同步。
def get_ui() -> dict:
    return _settings.get("ui") or {}


def set_ui(cfg: dict) -> dict:
    if not isinstance(cfg, dict):
        raise ValueError("設定必須是物件")
    _settings["ui"] = cfg
    _save()
    return _settings["ui"]


# ---- Web 搜尋設定 ----
def get_web() -> dict:
    return _settings.get("web") or _default_web()


def set_web(cfg: dict) -> dict:
    cur = get_web()
    provider = cfg.get("provider", cur["provider"])
    if provider not in ("duckduckgo", "searxng"):
        raise ValueError("provider 必須是 duckduckgo 或 searxng")
    updated = {
        "provider": provider,
        "searxng_url": (cfg.get("searxng_url", cur.get("searxng_url")) or "").strip(),
        "max_results": int(cfg.get("max_results", cur.get("max_results")) or 5),
        "fetch_max_chars": int(
            cfg.get("fetch_max_chars", cur.get("fetch_max_chars")) or 6000
        ),
    }
    if provider == "searxng" and not updated["searxng_url"]:
        raise ValueError("SearXNG 需要填寫網址")
    _settings["web"] = updated
    _save()
    return updated
