"""執行期可切換、且持久化的應用設定（目前：圖片儲存目錄）。

- image_dir：生成圖片儲存與服務的目錄，可在 UI 中切換。
- known_dirs：歷來用過的目錄；切換後舊圖仍能被 /images 服務找到。
設定存於 DATA_DIR/app_settings.json（DATA_DIR 本身固定，不隨 image_dir 變動）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from config import DATA_DIR, IMAGE_DIR as DEFAULT_IMAGE_DIR, OLLAMA_URL, A1111_URL

SETTINGS_FILE = DATA_DIR / "app_settings.json"

# 每個服務來源：mode="api"(直接網址) 或 "docker"(容器名+容器內 port)
def _default_source(url: str, port: int) -> dict:
    return {"mode": "api", "url": url, "container": "", "port": port}


def _default_web() -> dict:
    return {
        "provider": "duckduckgo",  # duckduckgo | searxng
        "searxng_url": "",
        "max_results": 5,
        "fetch_max_chars": 6000,
    }


_settings: dict = {
    "image_dir": str(DEFAULT_IMAGE_DIR),
    "known_dirs": [str(DEFAULT_IMAGE_DIR)],
    "sources": {
        "ollama": _default_source(OLLAMA_URL, 11434),
        "a1111": _default_source(A1111_URL, 7860),
    },
    "web": _default_web(),
}


def _normalize_sources() -> None:
    """確保 sources 結構完整（補齊缺欄位）。"""
    defaults = {
        "ollama": _default_source(OLLAMA_URL, 11434),
        "a1111": _default_source(A1111_URL, 7860),
    }
    src = _settings.setdefault("sources", {})
    for svc, dflt in defaults.items():
        cur = src.get(svc) or {}
        src[svc] = {**dflt, **cur}


def _save() -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(_settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load() -> dict:
    """啟動時載入；確保目前目錄存在。"""
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _settings.update(data)
        except Exception:
            pass
    _settings.setdefault("known_dirs", [])
    if _settings["image_dir"] not in _settings["known_dirs"]:
        _settings["known_dirs"].insert(0, _settings["image_dir"])
    _normalize_sources()
    _settings["web"] = {**_default_web(), **(_settings.get("web") or {})}
    try:
        Path(_settings["image_dir"]).mkdir(parents=True, exist_ok=True)
    except Exception:
        # 目錄無法建立時退回預設
        _settings["image_dir"] = str(DEFAULT_IMAGE_DIR)
        Path(_settings["image_dir"]).mkdir(parents=True, exist_ok=True)
    return _settings


def get_image_dir() -> Path:
    return Path(_settings["image_dir"])


def set_image_dir(path: str) -> Path:
    """切換儲存目錄；會建立目錄並檢查可寫。"""
    p = Path(path).expanduser()
    if not p.is_absolute():
        raise ValueError("請提供絕對路徑")
    p.mkdir(parents=True, exist_ok=True)
    if not os.access(p, os.W_OK):
        raise PermissionError("此資料夾無法寫入")
    p_str = str(p.resolve())
    _settings["image_dir"] = p_str
    if p_str not in _settings["known_dirs"]:
        _settings["known_dirs"].insert(0, p_str)
    _save()
    return p


def find_image(filename: str) -> Path | None:
    """在目前與歷來目錄中尋找圖片檔（供 /images 服務，避免切換後舊圖失聯）。"""
    name = Path(filename).name  # 防止路徑穿越
    candidates = [_settings["image_dir"], *_settings.get("known_dirs", [])]
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
        "writable": os.access(d, os.W_OK),
        "count": count,
        "known_dirs": _settings.get("known_dirs", []),
    }


# ---- 服務來源（Ollama / A1111）----
def effective_url(source: dict) -> str:
    """由來源設定算出實際要連的 URL。"""
    if source.get("mode") == "docker" and source.get("container"):
        return f"http://{source['container']}:{source.get('port')}".rstrip("/")
    return (source.get("url") or "").rstrip("/")


def get_ollama_url() -> str:
    return effective_url(_settings["sources"]["ollama"])


def get_a1111_url() -> str:
    return effective_url(_settings["sources"]["a1111"])


def get_sources() -> dict:
    """回傳來源設定 + 算出的有效 URL（給前端顯示）。"""
    out = {}
    for svc, s in _settings["sources"].items():
        out[svc] = {**s, "effective_url": effective_url(s)}
    return out


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
    _settings["sources"][service] = updated
    _save()
    return {**updated, "effective_url": effective_url(updated)}


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
