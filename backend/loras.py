"""LoRA 清單 + 觸發詞。

向 A1111 讀 /sdapi/v1/loras，從安全張量內嵌的 kohya metadata（ss_tag_frequency）
萃取觸發詞，提供搜尋與「直接帶入 / 生圖」用的 prompt。對齊 booru_characters 的介面。

回傳格式：{name, alias, triggers, prompt, base, base_model, base_inferred, source, category}
  - name    : 丟給 <lora:NAME:1> 的名稱（A1111 的 loras 名稱，可能含子資料夾）。
  - alias   : 顯示用別名（沒有就用 name）。
  - triggers: 觸發詞清單（依訓練標籤頻率由高到低，已把底線換成空白）。
  - prompt  : 可直接帶入 / 生圖的字串 = <lora:NAME:1> + 觸發詞（略過太泛用的，
              以及 blush / smile / open mouth 這類表情標籤——角色 LoRA 的高頻訓練
              標籤常含這些，固定帶入會把每張圖的表情釘死；見 expression_tags）。
  - base / base_model / base_inferred / source / category：底模群組、Civitai 上標的底模、
              底模是否只是從訓練資訊推斷、Civitai 來源、內容分類（見 lora_meta）。

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
from collections import Counter
from typing import Any

import httpx

import a1111_client
import lora_meta
import settings_store
from config import DATA_DIR
from expression_tags import is_expression_tag

_CACHE_TTL = 60  # 秒；此區間內重用快取，避免逐鍵打 A1111
_TRIGGER_LIMIT = 12  # 每個 LoRA 最多保留幾個觸發詞

_items: list[dict[str, Any]] | None = None
_fetched_at = 0.0
_sources: list[dict[str, Any]] = []  # 有 Civitai 來源的 LoRA 的 source（分類標籤要抓的對象）
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
# 表情類的成人向標籤，expression_tags 白名單不列（不給分鏡 LLM 挑），但同樣不該固定帶入
_EXPRESSION_EXTRA = {"ahegao", "naughty face", "torogao", "aroused"}


def _skip_in_prompt(tag: str) -> bool:
    t = tag.lower()
    return t in _GENERIC or t in _EXPRESSION_EXTRA or is_expression_tag(t)


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
        useful = [t for t in triggers if not _skip_in_prompt(t)]
        tag = f"<lora:{name}:1>"
        prompt = ", ".join([tag, *useful]) if useful else tag
        paths[name] = lo.get("path") or ""
        inferred = lora_meta.infer_base(lo.get("metadata"))
        out.append(
            {
                "name": name,
                "alias": alias,
                "triggers": triggers,
                "prompt": prompt,
                "base": inferred,
                "base_model": inferred or "",
                "base_inferred": bool(inferred),
                "source": None,
            }
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
    items = _enrich(raw)
    await _attach_sources(items)
    _items = items
    _fetched_at = time.time()
    return _items


async def _attach_sources(items: list[dict[str, Any]]) -> None:
    """合併 Civitai Helper 的來源資料（底模以 Civitai 標的為準）。分類標籤不在這裡抓（只手動更新）。"""
    global _sources
    inv = await lora_meta.inventory()
    sources = []
    for it in items:
        c = inv.get(_path_by_name.get(it["name"]) or "")
        if not c:
            continue
        src = lora_meta.source_of(c)
        it["source"] = src
        base = lora_meta.normalize_base(src["base_model"])
        if base:
            it.update(base=base, base_model=src["base_model"], base_inferred=False)
        sources.append(src)
    _sources = sources


def _live(it: dict[str, Any]) -> dict[str, Any]:
    """補上分類與作者（每次回傳時才查快取，手動更新後不必等清單快取過期）。"""
    src = it.get("source")
    if not src:
        return {**it, "category": None}
    return {
        **it,
        "category": lora_meta.category(src["model_id"]),
        "source": {**src, "creator": lora_meta.creator(src["model_id"])},
    }


def refresh_categories() -> dict[str, Any]:
    """「更新分類」：全部重新向 Civitai 查標籤（背景），回傳進度。"""
    lora_meta.refresh_all(_sources)
    return lora_meta.status(_sources)


async def refresh_one(name: str) -> dict[str, Any]:
    """LoRA 詳情的「更新」：重讀 A1111 與 Civitai Helper 的資料（例如剛掃描過），
    重抓這個模型的 Civitai 標籤（分類、作者），預覽圖快取也作廢。回傳更新後的項目。"""
    try:
        items = await _ensure(force=True)
    except Exception:
        raise LoraError("連不到 A1111")
    it = next((x for x in items if x["name"] == name), None)
    if not it:
        raise LoraError(f"找不到 LoRA：{name}", 404)
    key = hashlib.sha1(name.encode("utf-8")).hexdigest()[:16]
    for f in _THUMB_DIR.glob(f"{key}_*.jpg"):
        f.unlink(missing_ok=True)
    _no_preview.discard(name)
    ok = await lora_meta.refresh_one(it["source"]) if it.get("source") else True
    return {**_live(it), "civitai_ok": ok}


def meta_status() -> dict[str, Any]:
    """分類標籤的狀態：抓取中＝這一輪的進度；否則＝已有分類的模型數 / 全部。"""
    return lora_meta.status(_sources)


async def search(q: str, limit: int | None = None) -> list[dict[str, Any]]:
    """關鍵字搜尋：正規化後多詞 AND（比對名稱 / 別名 / 觸發詞）；別名前綴優先。
    limit=None 代表不限制，回傳全部符合的 LoRA。"""
    try:
        items = await _ensure()
    except Exception:
        items = _items or []  # A1111 連不到 → 用舊快取或空清單，不讓 UI 爆掉
    nq = _norm(q)
    if not nq:
        return [_live(it) for it in (items if limit is None else items[:limit])]
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
    out = [_live(it) for _, _, it in scored]
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


# ---- 範例圖 / 刪除（走 A1111 的 Civitai Helper 擴充 API：/civitai-helper/v1） ----

class LoraError(Exception):
    """給使用者看的錯誤（main.py 轉成 HTTP 錯誤訊息）。status 對應 HTTP 狀態碼。"""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


_lora_folder: str | None = None  # Civitai Helper 回報的 LoRA 資料夾（A1111 那邊的絕對路徑）


def _ch_url(path: str) -> str:
    return f"{settings_store.get_a1111_url()}/civitai-helper/v1{path}"


async def _ch_name(name: str) -> str:
    """A1111 的 LoRA 名稱 → Civitai Helper 認得的「相對 LoRA 資料夾的路徑」。
    只給檔名在不同子資料夾有同名檔時會對到別的模型，刪除時不能冒這個險，所以用相對路徑。"""
    global _lora_folder
    try:
        await _ensure()
    except Exception:
        pass
    path = _path_by_name.get(name)
    if not path:
        raise LoraError(f"找不到 LoRA：{name}", 404)
    if _lora_folder is None:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(_ch_url("/model-types"))
                r.raise_for_status()
                _lora_folder = next((t["folder"] for t in r.json() if t.get("type") == "lora"), "") or ""
        except (httpx.HTTPError, ValueError):
            raise LoraError("連不到 A1111 的 Civitai Helper 擴充（/civitai-helper/v1）")
    folder = (_lora_folder or "").rstrip("/")
    if folder and path.startswith(folder + "/"):
        return path[len(folder) + 1:]
    return os.path.basename(path)


async def examples(name: str) -> dict[str, Any]:
    """這個 LoRA 在 Civitai 上的範例圖（本地存好的優先走 /api/a1111-thumb 代理）＋提示詞。"""
    import civitai_examples

    rel = await _ch_name(name)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(_ch_url("/models/lora/examples"), params={"name": rel})
    except httpx.HTTPError:
        raise LoraError("連不到 A1111 的 Civitai Helper 擴充（/civitai-helper/v1）")
    if r.status_code == 404:
        detail = _detail(r)
        if detail == "Not Found":
            raise LoraError("A1111 沒有 Civitai Helper 的 HTTP API（需要 sss22213 版的 Civitai Helper）")
        raise LoraError(detail or f"找不到 LoRA：{name}", 404)
    if r.status_code >= 400:
        raise LoraError(_detail(r) or f"Civitai Helper 回應 {r.status_code}")
    d = r.json()
    return {
        "has_info": bool(d.get("has_info")),
        "model_name": d.get("model_name") or "",
        "version_name": d.get("version_name") or "",
        "base_model": d.get("base_model") or "",
        "trained_words": d.get("trained_words") or [],
        "items": civitai_examples.gallery_items(d.get("images") or []),
    }


async def download_examples(name: str) -> dict[str, Any]:
    """把這個 LoRA 在 Civitai 上的範例圖全部存到 A1111 的模型旁邊（<model>.example_NN.*），
    等 Civitai Helper 的背景工作做完才回傳。已存在的不重抓；遵守 Civitai Helper 的
    「Skip NSFW Preview Images」設定。"""
    rel = await _ch_name(name)
    body = {"type": "lora", "name": rel, "max_images": 0, "overwrite": False, "wait": True, "timeout": 600}
    try:
        async with httpx.AsyncClient(timeout=660) as client:
            r = await client.post(_ch_url("/download-examples"), json=body)
    except httpx.HTTPError:
        raise LoraError("連不到 A1111 的 Civitai Helper 擴充（/civitai-helper/v1）")
    if r.status_code >= 400:
        raise LoraError(_detail(r) or f"Civitai Helper 回應 {r.status_code}", 404 if r.status_code == 404 else 502)
    task = r.json()
    if task.get("status") == "error":
        raise LoraError(f"下載範例圖失敗：{task.get('error') or '未知錯誤'}")
    if task.get("status") != "done":
        raise LoraError("下載範例圖還在進行中（超過 10 分鐘），稍後重新打開這個 LoRA 看看", 504)
    res = task.get("result") or {}
    return {k: int(res.get(k) or 0) for k in ("downloaded", "existed", "skipped_nsfw", "failed", "with_info")}


def _detail(r: httpx.Response) -> str:
    try:
        return str((r.json() or {}).get("detail") or "")
    except ValueError:
        return r.text[:200]


async def delete(name: str) -> dict[str, Any]:
    """永久刪除一個 LoRA（模型檔、info、預覽圖、卡片 json、範例圖），再請 A1111 重掃清單。"""
    rel = await _ch_name(name)
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(_ch_url("/delete-model"), json={"type": "lora", "name": rel})
    except httpx.HTTPError:
        raise LoraError("連不到 A1111 的 Civitai Helper 擴充（/civitai-helper/v1）")
    if r.status_code == 404 and _detail(r) == "Not Found":
        raise LoraError(
            "Civitai Helper 還沒有刪除用的 API（/delete-model）：請更新 Civitai Helper 並重新啟動 WebUI", 501
        )
    if r.status_code >= 400:
        raise LoraError(_detail(r) or f"Civitai Helper 回應 {r.status_code}")
    out = r.json()
    # 這個 LoRA 的縮圖快取作廢；清單重掃（A1111 + 本地快取）
    key = hashlib.sha1(name.encode("utf-8")).hexdigest()[:16]
    for f in _THUMB_DIR.glob(f"{key}_*.jpg"):
        f.unlink(missing_ok=True)
    _no_preview.discard(name)
    try:
        await refresh()
    except Exception:
        pass
    return out


# ---------------- 給 LLM 的 LoRA 清單（技能工具 civitai_lora_inventory 的後處理） ----------------

UNCATEGORIZED = "uncategorized"  # 不在 Civitai 上、或分類還沒手動更新
CATEGORY_KEYS = (*lora_meta.CATEGORIES, "other", UNCATEGORIZED)
_MODEL_ID = re.compile(r"/models/(\d+)")


async def _facts_by_path() -> dict[str, dict[str, Any]]:
    """{A1111 端的絕對路徑: {base, category}}，和 LoRA 瀏覽器的篩選用同一份資料。"""
    try:
        items = await _ensure()
    except Exception:
        items = _items or []  # A1111 連不到 → 退回 Civitai Helper 自己的資料
    out: dict[str, dict[str, Any]] = {}
    for it in items:
        p = _path_by_name.get(it["name"])
        if p:
            live = _live(it)
            out[p] = {"base": live.get("base"), "category": live.get("category")}
    return out


async def llm_inventory(data: dict[str, Any], page: dict[str, Any]) -> str:
    """Civitai Helper 回的是符合 q 的全部 LoRA；這裡補上底模群組與內容分類，依 category / base
    篩選、分頁，並附上各分類 / 底模的數量，讓 LLM 先看分類分布再往下找。"""
    want_cat = str(page.get("category") or "").strip().lower() or None
    if want_cat and want_cat not in CATEGORY_KEYS:
        return f"Unknown category '{want_cat}'. Use one of: {', '.join(CATEGORY_KEYS)}."
    raw_base = str(page.get("base") or "").strip()
    want_base = (lora_meta.normalize_base(raw_base) or raw_base) if raw_base else None

    folder = str(data.get("folder") or "").rstrip("/")
    facts = await _facts_by_path()
    rows: list[dict[str, Any]] = []
    for it in data.get("items") or []:
        rel = "/".join(p for p in (str(it.get("subfolder") or "").strip("/"), str(it.get("name") or "")) if p)
        f = facts.get(f"{folder}/{rel}")
        if f is None:  # A1111 清單裡對不到 → 直接看 Civitai Helper 的欄位
            m = _MODEL_ID.search(str(it.get("model_url") or ""))
            f = {
                "base": lora_meta.normalize_base(it.get("base_model")),
                "category": lora_meta.category(m.group(1)) if m else None,
            }
        # base_model 換成底模群組；根目錄的 subfolder 與 has_preview 對挑選沒用，省字元
        row = {k: v for k, v in it.items() if k not in ("base_model", "has_preview") and not (k == "subfolder" and v == "/")}
        row["base"] = f["base"] or "unknown"
        row["category"] = f["category"] or UNCATEGORIZED
        rows.append(row)

    same_base = lambda r: not want_base or _norm(r["base"]) == _norm(want_base)  # noqa: E731
    same_cat = lambda r: not want_cat or r["category"] == want_cat  # noqa: E731
    hits = [r for r in rows if same_base(r) and same_cat(r)]
    limit = max(1, int(page.get("limit") or 15))
    offset = max(0, int(page.get("offset") or 0))
    items = hits[offset : offset + limit]
    out: dict[str, Any] = {
        "total": len(hits),
        "offset": offset,
        "count": len(items),
        "filters": {k: v for k, v in (("q", page.get("q")), ("category", want_cat), ("base", want_base)) if v},
        # 分類數量不受 category 篩選影響、底模數量不受 base 篩選影響，才看得出該往哪找
        "categories": dict(Counter(r["category"] for r in rows if same_base(r)).most_common()),
        "bases": dict(Counter(r["base"] for r in rows if same_cat(r)).most_common()),
    }
    notes = []
    in_base = [r for r in rows if same_base(r)]
    if rows and all(r["category"] == UNCATEGORIZED for r in rows):
        notes.append(
            "No LoRA has a category yet: categories are fetched from Civitai only when the user presses "
            "「更新分類」 (Update categories) in the app's LoRA browser. Search with q and base instead."
        )
    elif want_cat and want_cat != UNCATEGORIZED:
        n = sum(1 for r in in_base if r["category"] == UNCATEGORIZED)
        if n:
            notes.append(
                f"{n} LoRAs have no category (not on Civitai, or not fetched yet) and are not included; "
                "if nothing here fits, search them with category 'uncategorized' or with q only."
            )
    if notes:
        out["note"] = " ".join(notes)
    # 摘要在前、每個 LoRA 一行：省字元，超過工具的字元上限時也只截掉後面的 LoRA
    head = json.dumps(out, ensure_ascii=False, indent=1)[:-2]
    lines = ",\n".join("  " + json.dumps(r, ensure_ascii=False) for r in items)
    return f'{head},\n "items": [\n{lines}\n ]\n}}'
