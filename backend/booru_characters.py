"""WAI / Illustrious 角色關鍵字搜尋資料。

混合資料來源：
- 內建精選清單（booru_characters_seed.json，離線即可用；可含 series 與 aliases）。
- 開機後背景向 danbooru 抓「人氣角色 tag」(category=4) 快取到 DATA_DIR，
  讓清單大幅完整（預設抓約兩萬個）。抓取失敗（網路不通等）就只用內建清單。

回傳格式統一為 {tag, name, series}；tag 即丟給 A1111/WAI 的 danbooru 角色 tag。
搜尋採『正規化 + 多詞 AND + 別名』：
  - 正規化會收合日文長音（uu→u、ou→o…），所以 yuko 也能找到 yuuko；
  - 多個關鍵字需全部命中（"ganyu genshin" 可用）；
  - 精選清單可加 aliases（暱稱/作品別名），讓 shamiko、machikado 也找得到。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any

import httpx

from config import DATA_DIR

_SEED_FILE = os.path.join(os.path.dirname(__file__), "booru_characters_seed.json")
# Drawing Spells（MIT，Copyright 2025 深海異音；https://github.com/hbl917070/DrawingSpells）
# 一萬四千多個 Illustrious/NoobAI 角色，附完整服飾提示詞 → 生成更準。
_DRAWINGSPELLS_FILE = os.path.join(os.path.dirname(__file__), "drawingspells_characters.json")
_CACHE_FILE = DATA_DIR / "booru_characters_cache.json"
_CACHE_TTL = 30 * 24 * 3600  # 30 天內不重抓
_CACHE_VERSION = 2           # 改抓取規模/格式時 +1，舊快取會自動失效重抓
_DANBOORU = "https://danbooru.donmai.us/tags.json"
_UA = "webui-gen-image/1.0 (character tag search)"

_lock = threading.Lock()
_combined_cache: list[dict[str, str]] | None = None
_norm_cache: list[tuple[str, str]] | None = None  # 對齊 _combined_cache：(name_norm, haystack_norm)


# ---- 正規化（讓羅馬拼音變體也能命中） ----------------------------------------
_VOWEL_PAIRS = (("ou", "o"), ("oo", "o"), ("uu", "u"), ("ii", "i"), ("ee", "e"), ("aa", "a"))
_NONALNUM = re.compile(r"[^a-z0-9]+")


def _norm(s: str) -> str:
    s = (s or "").lower()
    for a, b in _VOWEL_PAIRS:
        s = s.replace(a, b)
    return " ".join(_NONALNUM.sub(" ", s).split())


def _load_seed() -> list[dict[str, Any]]:
    try:
        with open(_SEED_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _load_drawingspells() -> list[dict[str, Any]]:
    """Drawing Spells 角色（含完整提示詞 prompt）。檔案不在就跳過。"""
    try:
        with open(_DRAWINGSPELLS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _display_from_tag(tag: str) -> tuple[str, str]:
    """從 danbooru tag 推出顯示名與作品名，例如 ganyu_(genshin_impact) → (Ganyu, Genshin Impact)。"""
    base, series = tag, ""
    if tag.endswith(")") and "_(" in tag:
        i = tag.rfind("_(")
        base, series = tag[:i], tag[i + 2 : -1]
    titlecase = lambda s: " ".join(w[:1].upper() + w[1:] for w in s.replace("_", " ").split())
    return titlecase(base), titlecase(series)


def _load_cache() -> list[dict[str, Any]]:
    try:
        with open(_CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("version") != _CACHE_VERSION:
            return []  # 舊版快取（資料太少）→ 視為無，觸發重抓
        return data.get("items") or []
    except Exception:
        return []


def _combined() -> list[dict[str, str]]:
    """精選 + Drawing Spells + danbooru 快取，全部保留（不去重）。
    刻意不去重：同一角色在不同來源的搜尋關鍵字/提示詞不一定相同，去掉會漏掉變體。
    同時建立對齊的正規化索引 _norm_cache 供快速搜尋。"""
    global _combined_cache, _norm_cache
    if _combined_cache is not None:
        return _combined_cache
    out: list[dict[str, str]] = []
    norms: list[tuple[str, str]] = []
    # 順序：精選（有別名）→ Drawing Spells（有完整提示詞）→ danbooru 快取（純 tag）
    for item in _load_seed() + _load_drawingspells() + _load_cache():
        tag = (item.get("tag") or "").strip()
        if not tag:
            continue
        name = item.get("name") or _display_from_tag(tag)[0]
        series = item.get("series") or _display_from_tag(tag)[1]
        aliases = item.get("aliases") or []
        entry = {"tag": tag, "name": name, "series": series}
        if item.get("prompt"):
            entry["prompt"] = item["prompt"]  # 完整服飾提示詞，生成時優先用
        out.append(entry)
        hay = _norm(" ".join([name, series, tag.replace("_", " "), " ".join(aliases)]))
        norms.append((_norm(name), hay))
    _combined_cache = out
    _norm_cache = norms
    return out


def search(q: str, limit: int = 60) -> list[dict[str, str]]:
    """關鍵字搜尋：正規化後多詞 AND 命中；名稱前綴/包含優先，其餘依人氣序。"""
    items = _combined()
    norms = _norm_cache or []
    nq = _norm(q)
    if not nq:
        return items[:limit]
    tokens = nq.split()
    scored: list[tuple[int, int, dict[str, str]]] = []
    for i, it in enumerate(items):
        name_n, hay = norms[i]
        if not all(tok in hay for tok in tokens):
            continue
        rank = 0 if name_n.startswith(nq) else (1 if nq in name_n else 2)
        scored.append((rank, i, it))
    scored.sort(key=lambda s: (s[0], s[1]))
    return [it for _, _, it in scored[:limit]]


def _fetch_danbooru(pages: int = 20, per_page: int = 1000, min_posts: int = 20) -> list[dict[str, str]]:
    """抓人氣角色 tag（category=4，依貼文數排序，約取前兩萬）。失敗時拋出，由呼叫端吞掉。"""
    items: list[dict[str, str]] = []
    with httpx.Client(timeout=20, headers={"User-Agent": _UA}) as client:
        for page in range(1, pages + 1):
            try:
                resp = client.get(
                    _DANBOORU,
                    params={
                        "search[category]": 4,
                        "search[order]": "count",
                        "limit": per_page,
                        "page": page,
                    },
                )
                resp.raise_for_status()
                batch = resp.json()
            except Exception:
                break  # 中途被限流/出錯 → 保留已抓到的，不要整批丟失
            if not batch:
                break
            for t in batch:
                name_tag = (t.get("name") or "").strip()
                if not name_tag or (t.get("post_count") or 0) < min_posts:
                    continue
                disp, series = _display_from_tag(name_tag)
                items.append({"tag": name_tag, "name": disp, "series": series})
            time.sleep(0.25)  # 客氣一點，避免被限流
    return items


def ensure_enriched() -> None:
    """背景補齊：快取過期/不存在/版本不符時向 danbooru 抓一次。任何錯誤都靜默跳過。"""
    global _combined_cache, _norm_cache
    try:
        try:
            mtime = os.path.getmtime(_CACHE_FILE)
            if time.time() - mtime < _CACHE_TTL and _load_cache():
                return  # 快取仍新鮮且版本相符
        except OSError:
            pass
        items = _fetch_danbooru()
        if not items:
            return
        with _lock:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {"version": _CACHE_VERSION, "fetched_at": time.time(), "items": items},
                    f,
                    ensure_ascii=False,
                )
            _combined_cache = None  # 失效，下次 search 重新合併
            _norm_cache = None
    except Exception:
        pass  # danbooru 連不到等 → 只用內建清單
