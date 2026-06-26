"""LoRA 清單 + 觸發詞。

向 A1111 讀 /sdapi/v1/loras，從安全張量內嵌的 kohya metadata（ss_tag_frequency）
萃取觸發詞，提供搜尋與「直接帶入 / 生圖」用的 prompt。對齊 booru_characters 的介面。

回傳格式：{name, alias, triggers, prompt}
  - name    : 丟給 <lora:NAME:1> 的名稱（A1111 的 loras 名稱，可能含子資料夾）。
  - alias   : 顯示用別名（沒有就用 name）。
  - triggers: 觸發詞清單（依訓練標籤頻率由高到低，已把底線換成空白）。
  - prompt  : 可直接帶入 / 生圖的字串 = <lora:NAME:1> + 觸發詞（略過太泛用的）。

快取策略：記憶體內 TTL 快取（LoRA 清單變動不頻繁），避免每次按鍵都打 A1111；
設定頁換了 A1111 位址、或使用者新增了 LoRA，可用 refresh() 強制重抓。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import time
from typing import Any

import a1111_client
from config import DATA_DIR

_CACHE_TTL = 60  # 秒；此區間內重用快取，避免逐鍵打 A1111
_TRIGGER_LIMIT = 12  # 每個 LoRA 最多保留幾個觸發詞

_items: list[dict[str, Any]] | None = None
_fetched_at = 0.0
# name → A1111 那邊的 .safetensors 絕對路徑（縮圖要用；不外送給前端避免洩漏路徑）
_path_by_name: dict[str, str] = {}

# ---- 縮圖（代理 A1111 /sd_extra_networks/thumb，Pillow 縮放後快取） ----
_THUMB_DIR = DATA_DIR / "lora_thumbs"
_IMG_EXT = ("png", "jpg", "jpeg", "webp", "gif")
_no_preview: set[str] = set()  # 確定沒有預覽圖的 name，省得一直重探

_NONALNUM = re.compile(r"[^a-z0-9]+")
# 太泛用、放進 prompt 幫助不大的標籤（顯示時仍保留，只在建構 prompt 時略過）
_GENERIC = {
    "1girl", "1boy", "2girls", "solo", "looking at viewer", "simple background",
    "white background", "masterpiece", "best quality", "highres", "absurdres",
}


def _norm(s: str) -> str:
    return " ".join(_NONALNUM.sub(" ", (s or "").lower()).split())


def _parse_tag_frequency(meta: dict[str, Any]) -> list[str]:
    """從 ss_tag_frequency 取出依頻率排序的觸發詞。
    結構為 {資料集名: {標籤: 次數}}，值可能是 JSON 字串或已解析的 dict。"""
    raw = (meta or {}).get("ss_tag_frequency")
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    if not isinstance(raw, dict):
        return []
    counts: dict[str, int] = {}
    for dataset in raw.values():
        if not isinstance(dataset, dict):
            continue
        for tag, n in dataset.items():
            tag = (tag or "").strip()
            if not tag:
                continue
            try:
                counts[tag] = counts.get(tag, 0) + int(n)
            except (TypeError, ValueError):
                pass
    # 依次數由高到低；底線換空白（符合 anime 模型 prompt 慣例）；去重
    out: list[str] = []
    seen: set[str] = set()
    for tag, _n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True):
        disp = tag.replace("_", " ").strip()
        key = disp.lower()
        if not disp or key in seen:
            continue
        seen.add(key)
        out.append(disp)
        if len(out) >= _TRIGGER_LIMIT:
            break
    return out


def _enrich(raw_loras: list[dict[str, Any]]) -> list[dict[str, Any]]:
    global _path_by_name
    out: list[dict[str, Any]] = []
    paths: dict[str, str] = {}
    for lo in raw_loras:
        name = (lo.get("name") or "").strip()
        if not name:
            continue
        alias = (lo.get("alias") or "").strip() or name
        triggers = _parse_tag_frequency(lo.get("metadata") or {})
        useful = [t for t in triggers if t.lower() not in _GENERIC]
        tag = f"<lora:{name}:1>"
        prompt = ", ".join([tag, *useful]) if useful else tag
        paths[name] = lo.get("path") or ""
        out.append(
            {"name": name, "alias": alias, "triggers": triggers, "prompt": prompt}
        )
    out.sort(key=lambda x: x["alias"].lower())
    _path_by_name = paths
    return out


async def _ensure(force: bool = False) -> list[dict[str, Any]]:
    global _items, _fetched_at
    fresh = _items is not None and (time.time() - _fetched_at) < _CACHE_TTL
    if fresh and not force:
        return _items
    raw = await a1111_client.list_loras()
    _items = _enrich(raw)
    _fetched_at = time.time()
    return _items


async def search(q: str, limit: int | None = None) -> list[dict[str, Any]]:
    """關鍵字搜尋：正規化後多詞 AND（比對名稱 / 別名 / 觸發詞）；別名前綴優先。
    limit=None 代表不限制，回傳全部符合的 LoRA。"""
    try:
        items = await _ensure()
    except Exception:
        items = _items or []  # A1111 連不到 → 用舊快取或空清單，不讓 UI 爆掉
    nq = _norm(q)
    if not nq:
        return items if limit is None else items[:limit]
    tokens = nq.split()
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for i, it in enumerate(items):
        hay = _norm(" ".join([it["name"], it["alias"], " ".join(it["triggers"])]))
        if not all(tok in hay for tok in tokens):
            continue
        alias_n = _norm(it["alias"])
        rank = 0 if alias_n.startswith(nq) else (1 if nq in alias_n else 2)
        scored.append((rank, i, it))
    scored.sort(key=lambda s: (s[0], s[1]))
    out = [it for _, _, it in scored]
    return out if limit is None else out[:limit]


async def refresh() -> list[dict[str, Any]]:
    """請 A1111 重掃 LoRA 目錄並強制重建快取。連不到時由呼叫端處理例外。"""
    await a1111_client.refresh_loras()
    _no_preview.clear()  # 新增的 LoRA 可能有預覽圖了 → 重新探
    return await _ensure(force=True)


def _preview_candidates(path: str) -> list[str]:
    """依 A1111 find_preview 慣例組候選預覽路徑：<base>.preview.<ext> 優先，再退 <base>.<ext>。"""
    base = os.path.splitext(path)[0]
    return [f"{base}.preview.{e}" for e in _IMG_EXT] + [f"{base}.{e}" for e in _IMG_EXT]


async def thumb_file(name: str, size: int = 256) -> str | None:
    """回傳該 LoRA 縮圖的本機快取路徑；沒有預覽圖回 None（前端改顯示首字母佔位）。
    流程：先看磁碟快取 → 代理 A1111 取原圖 → Pillow 縮放後快取。"""
    key = hashlib.sha1(name.encode("utf-8")).hexdigest()[:16]
    cache = _THUMB_DIR / f"{key}_{size}.jpg"
    if cache.is_file():
        return str(cache)
    if name in _no_preview:
        return None
    try:
        await _ensure()  # 確保 _path_by_name 已載入
    except Exception:
        pass
    path = _path_by_name.get(name)
    if not path:
        _no_preview.add(name)
        return None
    raw = await a1111_client.fetch_lora_preview(_preview_candidates(path))
    if not raw:
        _no_preview.add(name)
        return None
    try:
        from PIL import Image

        _THUMB_DIR.mkdir(parents=True, exist_ok=True)
        with Image.open(io.BytesIO(raw)) as im:
            im = im.convert("RGB")
            im.thumbnail((size, size), Image.LANCZOS)
            im.save(cache, "JPEG", quality=82)
        return str(cache)
    except Exception:
        _no_preview.add(name)  # 壞圖／無法解碼 → 別一直重抓
        return None
