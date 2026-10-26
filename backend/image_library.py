"""圖片庫：瀏覽生成過的圖、縮圖、詳細資訊（PNG 文字區塊 / EXIF）、用在哪裡、刪除到垃圾桶 / 還原。

圖片在 settings_store 的圖片資料夾（目前、預設、歷來用過的）；只接受這些資料夾裡的檔名，不能刪到別處的檔案。
- 索引：IMAGE_CACHE_DIR/index-<資料夾代號>.json，記每張圖的尺寸與生成參數（搜尋用），依大小 / mtime 增量更新。
- 縮圖：IMAGE_CACHE_DIR/thumbs/<資料夾代號>/<檔名>_<尺寸>.jpg。
- 垃圾桶：IMAGE_TRASH_DIR/<檔名> + trash.json（原本的資料夾、刪除時間），可還原或永久刪除。
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import a1111_client
import comics_store
import conversations_store
import settings_store
from config import IMAGE_CACHE_DIR, IMAGE_DIR, IMAGE_TRASH_DIR, LANGGRAPH_RUNS_DIR

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~-]{0,200}\.(png|jpe?g|webp)$", re.I)
# 對話 / 漫畫 / 工作流紀錄裡引用圖片的方式（相對或完整網址都算）
_REF_RE = re.compile(r"/images/([A-Za-z0-9][A-Za-z0-9._-]{0,200}\.(?:png|jpe?g|webp))", re.I)
KINDS = ("generated", "comic", "upload")
SORTS = ("new", "old", "large")
_PROMPT_MAX = 3000
_TEXT_MAX = 200_000  # 單一文字區塊最多回傳的字數（ComfyUI workflow JSON 可能很長）

_index: dict[str, dict[str, dict[str, Any]]] = {}
_index_lock = threading.Lock()
_trash_lock = threading.Lock()
_refs_cache: tuple[float, dict[str, list[dict[str, Any]]]] | None = None
_REFS_TTL = 10.0


def kind_of(name: str) -> str:
    if name.startswith("comic_"):
        return "comic"  # 漫畫工作室匯出的整頁
    if name.startswith("panel_"):
        return "upload"  # 漫畫 / 說故事上傳的圖
    return "generated"


# ---------------- 資料夾 ----------------

def folders() -> list[dict[str, Any]]:
    """可以瀏覽的圖片資料夾：目前、預設、歷來用過的自訂資料夾。"""
    cur = settings_store.get_image_dir().resolve()
    default = IMAGE_DIR.resolve()
    out, seen = [], set()
    for p in (cur, default, *(Path(d) for d in settings_store.known_image_dirs())):
        s = str(p)
        if s in seen:
            continue
        seen.add(s)
        out.append({"path": s, "current": p == cur, "default": p == default, "exists": p.is_dir()})
    return out


def resolve_folder(folder: str | None) -> Path:
    if not folder:
        return settings_store.get_image_dir().resolve()
    for f in folders():
        if f["path"] == folder:
            return Path(folder)
    raise PermissionError("這不是圖片資料夾")


def folder_key(path: Path) -> str:
    return "default" if path.resolve() == IMAGE_DIR.resolve() else hashlib.sha1(str(path).encode()).hexdigest()[:10]


def valid_name(name: str) -> str:
    if not _NAME_RE.match(name or "") or name != Path(name).name:
        raise ValueError(f"不合法的檔名：{name}")
    return name


def image_path(folder: str | None, name: str) -> Path:
    path = resolve_folder(folder) / valid_name(name)
    if not path.is_file():
        raise FileNotFoundError("找不到這張圖")
    return path


# ---------------- 讀 metadata ----------------

def _short(v: Any) -> str:
    if isinstance(v, (bytes, bytearray)):
        return f"<{len(v)} bytes>"
    return str(v)[:500]


def _decode_user_comment(raw: Any) -> str:
    """EXIF UserComment：前 8 bytes 是編碼（A1111 存 JPEG / WebP 用 UNICODE，大小端不一定）。"""
    if isinstance(raw, str):
        return raw.strip("\x00")
    if not isinstance(raw, (bytes, bytearray)):
        return str(raw)
    head, body = bytes(raw[:8]), bytes(raw[8:])
    if head.startswith(b"UNICODE"):
        best = ""
        for enc in ("utf-16-be", "utf-16-le"):
            with contextlib.suppress(UnicodeDecodeError):
                s = body.decode(enc)
                # 提示詞幾乎都是 ASCII：解錯邊時會變成一堆 CJK 字，挑 ASCII 比例高的
                if sum(c < "\x80" for c in s) > sum(c < "\x80" for c in best):
                    best = s
        return best.strip("\x00")
    if head.startswith(b"ASCII") or head == b"\x00" * 8:
        return body.decode("utf-8", "replace").strip("\x00")
    return bytes(raw).decode("utf-8", "replace").strip("\x00")


def _exif(im: Any) -> tuple[dict[str, str], str]:
    """(可讀的 EXIF 欄位, UserComment 裡的生成參數)"""
    from PIL import ExifTags

    out: dict[str, str] = {}
    params = ""
    try:
        exif = im.getexif()
    except Exception:
        return out, params
    for tag, val in exif.items():
        if tag != 0x8769:
            out[ExifTags.TAGS.get(tag, hex(tag))] = _short(val)
    try:
        sub = exif.get_ifd(0x8769)
    except Exception:
        sub = {}
    for tag, val in sub.items():
        name = ExifTags.TAGS.get(tag, hex(tag))
        if tag == 0x9286:  # UserComment
            params = _decode_user_comment(val).strip()
            out[name] = params
        else:
            out[name] = _short(val)
    return out, params


def _read(path: Path, full: bool) -> dict[str, Any]:
    """full=False（建索引）只讀檔頭；full=True（詳細資訊）連 IDAT 之後的文字區塊與 EXIF 都讀。"""
    from PIL import Image

    texts: dict[str, str] = {}
    other: dict[str, str] = {}
    exif: dict[str, str] = {}
    params = ""
    with Image.open(path) as im:
        w, h = im.size
        fmt, mode = im.format, im.mode
        if full and fmt == "PNG":
            with contextlib.suppress(Exception):
                texts = {k: str(v) for k, v in im.text.items()}
        for k, v in im.info.items():
            if isinstance(v, str):
                texts.setdefault(k, v)
            elif k == "comment" and isinstance(v, bytes):  # JPEG COM 區塊
                texts.setdefault(k, v.decode("utf-8", "replace"))
            elif k != "exif" and not k.startswith("jfif"):  # JFIF 檔頭欄位對人沒意義
                other[k] = _short(v)
        if full or fmt != "PNG":
            exif, params = _exif(im)
    params = texts.get("parameters") or params
    return {"w": w, "h": h, "format": fmt, "mode": mode, "texts": texts, "other": other,
            "exif": exif, "parameters": params.strip()}


def _index_entry(path: Path, st: os.stat_result) -> dict[str, Any]:
    entry: dict[str, Any] = {"s": st.st_size, "m": st.st_mtime, "k": kind_of(path.name)}
    try:
        meta = _read(path, full=False)
    except Exception:
        return {**entry, "w": 0, "h": 0, "bad": True}
    parsed = a1111_client.parse_geninfo(meta["parameters"]) if meta["parameters"] else {}
    params = parsed.get("params") or {}
    entry.update({
        "w": meta["w"], "h": meta["h"], "meta": bool(meta["parameters"] or meta["texts"]),
        "p": (parsed.get("prompt") or "")[:_PROMPT_MAX],
        "model": params.get("Model", ""), "seed": params.get("Seed", ""),
    })
    return entry


# ---------------- 索引 ----------------

def _index_path(key: str) -> Path:
    return IMAGE_CACHE_DIR / f"index-{key}.json"


def _load_index(key: str) -> dict[str, dict[str, Any]]:
    if key not in _index:
        try:
            _index[key] = json.loads(_index_path(key).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _index[key] = {}
    return _index[key]


def _save_index(key: str, idx: dict[str, dict[str, Any]]) -> None:
    IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _index_path(key).with_suffix(".tmp")
    tmp.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_index_path(key))


def scan(folder: Path) -> dict[str, dict[str, Any]]:
    """資料夾裡所有圖片的索引；新圖或改過的圖才重讀 metadata。"""
    key = folder_key(folder)
    with _index_lock:
        idx = _load_index(key)
        seen: dict[str, dict[str, Any]] = {}
        changed = False
        with contextlib.suppress(FileNotFoundError, NotADirectoryError):
            with os.scandir(folder) as it:
                for e in it:
                    if not _NAME_RE.match(e.name) or not e.is_file():
                        continue
                    st = e.stat()
                    ent = idx.get(e.name)
                    if not ent or ent.get("s") != st.st_size or ent.get("m") != st.st_mtime:
                        ent = _index_entry(Path(e.path), st)
                        changed = True
                    seen[e.name] = ent
        if changed or len(seen) != len(idx):
            _index[key] = seen
            _save_index(key, seen)
        return seen


def _forget(folder: Path, names: list[str]) -> None:
    key = folder_key(folder)
    with _index_lock:
        idx = _load_index(key)
        for n in names:
            idx.pop(n, None)
        _save_index(key, idx)
    for n in names:
        _drop_thumbs(key, n)


# ---------------- 用在哪裡 ----------------

def refs_map() -> dict[str, list[dict[str, Any]]]:
    """檔名 → 用到它的對話 / 漫畫作品 / 工作流紀錄（快取幾秒，列表和詳細資訊共用）。"""
    global _refs_cache
    now = time.monotonic()
    if _refs_cache and now - _refs_cache[0] < _REFS_TTL:
        return _refs_cache[1]
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str, str]] = set()

    def add(name: str, ref: dict[str, Any]) -> None:
        k = (name, ref["type"], f'{ref.get("project", "")}/{ref["id"]}')
        if k not in seen:
            seen.add(k)
            out[name].append(ref)

    for cid, title, text in conversations_store.scan_texts():
        for n in set(_REF_RE.findall(text or "")):
            add(n, {"type": "chat", "id": cid, "title": title or ""})
    for cid, title, text in comics_store.scan_texts():
        for n in set(_REF_RE.findall(text or "")):
            add(n, {"type": "comic", "id": cid, "title": title or ""})
    with contextlib.suppress(OSError):
        for f in LANGGRAPH_RUNS_DIR.glob("*/*/*.json"):
            with contextlib.suppress(OSError):
                for n in set(_REF_RE.findall(f.read_text(encoding="utf-8", errors="replace"))):
                    add(n, {"type": "workflow", "id": f.stem, "project": f.parent.name,
                            "folder_key": f.parent.parent.name})
    _refs_cache = (now, dict(out))
    return _refs_cache[1]


# ---------------- 列表 / 詳細資訊 ----------------

def _rows(path: Path) -> list[dict[str, Any]]:
    refs = refs_map()
    return [{"name": n, **e, "used": len(refs.get(n, ()))} for n, e in scan(path).items()]


def _filter(rows: list[dict[str, Any]], q: str, kind: str, usage: str) -> list[dict[str, Any]]:
    if kind in KINDS:
        rows = [r for r in rows if r["k"] == kind]
    if usage in ("used", "unused"):
        rows = [r for r in rows if bool(r["used"]) == (usage == "used")]
    terms = q.lower().split()
    if terms:
        rows = [r for r in rows
                if all(t in f'{r["name"]} {r.get("p", "")} {r.get("model", "")} {r.get("seed", "")}'.lower()
                       for t in terms)]
    return rows


def list_images(folder: str | None = None, *, q: str = "", kind: str = "", usage: str = "",
                sort: str = "new", offset: int = 0, limit: int = 60) -> dict[str, Any]:
    path = resolve_folder(folder)
    rows = _rows(path)
    counts = {"all": len(rows), **{k: 0 for k in KINDS}, "used": 0, "unused": 0}
    for r in rows:
        counts[r["k"]] += 1
        counts["used" if r["used"] else "unused"] += 1
    total_bytes = sum(r["s"] for r in rows)
    rows = _filter(rows, q, kind, usage)
    if sort == "large":
        rows.sort(key=lambda r: r["s"], reverse=True)
    else:
        rows.sort(key=lambda r: r["m"], reverse=(sort != "old"))
    offset, limit = max(0, offset), max(1, min(300, limit))
    page = [{
        "name": r["name"], "url": f'/images/{r["name"]}', "size": r["s"], "mtime": r["m"],
        "kind": r["k"], "w": r.get("w", 0), "h": r.get("h", 0), "prompt": (r.get("p") or "")[:240],
        "model": r.get("model", ""), "seed": r.get("seed", ""), "meta": bool(r.get("meta")),
        "used": r["used"], "bad": bool(r.get("bad")),
    } for r in rows[offset:offset + limit]]
    return {
        "folder": str(path), "folders": folders(), "items": page, "total": len(rows), "offset": offset,
        "counts": counts, "total_bytes": total_bytes, "trash": trash_count(),
    }


def list_names(folder: str | None = None, *, q: str = "", kind: str = "", usage: str = "") -> dict[str, Any]:
    """符合篩選的每一張（多選的「全選符合條件」用，還沒載入的也算）：檔名、大小、用到幾處。"""
    rows = _filter(_rows(resolve_folder(folder)), q, kind, usage)
    return {"items": [{"name": r["name"], "size": r["s"], "used": r["used"]} for r in rows], "total": len(rows)}


def info(folder: str | None, name: str) -> dict[str, Any]:
    path = image_path(folder, name)
    st = path.stat()
    meta = _read(path, full=True)
    parsed = a1111_client.parse_geninfo(meta["parameters"]) if meta["parameters"] else None
    texts = [{"key": k, "value": v[:_TEXT_MAX], "length": len(v)} for k, v in meta["texts"].items()]
    return {
        "name": name, "url": f"/images/{name}", "folder": str(path.parent), "path": str(path),
        "size": st.st_size, "mtime": st.st_mtime, "kind": kind_of(name),
        "w": meta["w"], "h": meta["h"], "format": meta["format"], "mode": meta["mode"],
        "texts": texts, "other": meta["other"], "exif": meta["exif"],
        "parameters": meta["parameters"], "parsed": parsed, "refs": refs_map().get(name, []),
    }


# ---------------- 縮圖 ----------------

def _thumb_dir(key: str) -> Path:
    return IMAGE_CACHE_DIR / "thumbs" / key


def _drop_thumbs(key: str, name: str) -> None:
    for f in _thumb_dir(key).glob(f"{glob_escape(name)}_*.jpg"):
        with contextlib.suppress(OSError):
            f.unlink()


def glob_escape(s: str) -> str:
    return re.sub(r"([*?\[])", r"[\1]", s)


def _make_thumb(src: Path, key: str, size: int) -> Path:
    from PIL import Image

    size = max(96, min(768, int(size)))
    cache = _thumb_dir(key) / f"{src.name}_{size}.jpg"
    with contextlib.suppress(OSError):
        if cache.stat().st_mtime >= src.stat().st_mtime:
            return cache
    cache.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im.draft("RGB", (size, size))  # JPEG 直接用小尺寸解碼
        w, h = im.size
        if h > w * 1.5:  # 很長的漫畫頁：只留上段，格子裡才看得出內容
            im = im.crop((0, 0, w, int(w * 1.5)))
            h = int(w * 1.5)
        scale = min(1.0, size / max(1, min(w, h)))  # 短邊縮到 size，格子用 object-cover 裁切
        im = im.convert("RGB").resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
        tmp = cache.with_name(f"{cache.name}.{threading.get_ident()}.tmp")
        im.save(tmp, "JPEG", quality=82)
        tmp.replace(cache)
    return cache


def thumb(folder: str | None, name: str, size: int = 384) -> Path:
    path = image_path(folder, name)
    return _make_thumb(path, folder_key(path.parent), size)


# ---------------- 刪除 / 垃圾桶 ----------------

def _trash_file() -> Path:
    return IMAGE_TRASH_DIR / "trash.json"


def _load_trash() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(_trash_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if (IMAGE_TRASH_DIR / k).is_file()} if isinstance(data, dict) else {}


def _save_trash(idx: dict[str, dict[str, Any]]) -> None:
    IMAGE_TRASH_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _trash_file().with_suffix(".tmp")
    tmp.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_trash_file())


def trash_count() -> int:
    with _trash_lock:
        return len(_load_trash())


def _trash_id(name: str, idx: dict[str, Any]) -> str:
    if name not in idx and not (IMAGE_TRASH_DIR / name).exists():
        return name
    stem, ext = os.path.splitext(name)
    n = 2
    while f"{stem}~{n}{ext}" in idx or (IMAGE_TRASH_DIR / f"{stem}~{n}{ext}").exists():
        n += 1
    return f"{stem}~{n}{ext}"


def delete(folder: str | None, names: list[str]) -> dict[str, Any]:
    """移到垃圾桶（可還原）。"""
    path = resolve_folder(folder)
    for n in names:
        valid_name(n)
    idx_entries = scan(path)
    moved, missing, trash_ids = [], [], []
    with _trash_lock:
        trash = _load_trash()
        IMAGE_TRASH_DIR.mkdir(parents=True, exist_ok=True)
        for n in dict.fromkeys(names):
            src = path / n
            if not src.is_file():
                missing.append(n)
                continue
            tid = _trash_id(n, trash)
            size = src.stat().st_size
            shutil.move(str(src), str(IMAGE_TRASH_DIR / tid))
            ent = idx_entries.get(n) or {}
            trash[tid] = {"name": n, "from": str(path), "deleted_at": time.time(), "size": size,
                          "kind": kind_of(n), "w": ent.get("w", 0), "h": ent.get("h", 0),
                          "prompt": (ent.get("p") or "")[:240]}
            moved.append(n)
            trash_ids.append(tid)
        _save_trash(trash)
    _forget(path, moved)
    # trash_ids：垃圾桶裡的編號（同名時會加 ~2），前端「復原」直接拿它還原這一批
    return {"deleted": moved, "missing": missing, "trash_ids": trash_ids}


def list_trash() -> dict[str, Any]:
    with _trash_lock:
        trash = _load_trash()
    items = [{"id": k, **v} for k, v in trash.items()]
    items.sort(key=lambda r: r.get("deleted_at") or 0, reverse=True)
    return {"items": items, "total": len(items), "total_bytes": sum(r.get("size") or 0 for r in items)}


def trash_thumb(tid: str, size: int = 384) -> Path:
    src = IMAGE_TRASH_DIR / valid_name(tid)
    if not src.is_file():
        raise FileNotFoundError("垃圾桶裡沒有這張圖")
    return _make_thumb(src, "trash", size)


def restore(ids: list[str]) -> dict[str, Any]:
    """放回原本的資料夾（那個資料夾不能用了就放到目前的圖片資料夾）。"""
    allowed = {f["path"] for f in folders()}
    restored, failed = [], []
    with _trash_lock:
        trash = _load_trash()
        for tid in dict.fromkeys(ids):
            rec = trash.get(tid)
            if not rec or not _NAME_RE.match(tid):
                failed.append({"id": tid, "error": "垃圾桶裡沒有這張圖"})
                continue
            dest_dir = Path(rec.get("from") or "")
            if str(dest_dir) not in allowed or not dest_dir.is_dir() or not os.access(dest_dir, os.W_OK):
                dest_dir = settings_store.get_image_dir()
            dest = dest_dir / rec["name"]
            if dest.exists():
                failed.append({"id": tid, "error": f"{dest_dir} 已經有同名的圖"})
                continue
            shutil.move(str(IMAGE_TRASH_DIR / tid), str(dest))
            trash.pop(tid)
            _drop_thumbs("trash", tid)
            restored.append({"id": tid, "name": rec["name"], "folder": str(dest_dir)})
        _save_trash(trash)
    return {"restored": restored, "failed": failed}


def purge(ids: list[str] | None) -> dict[str, Any]:
    """永久刪除；ids=None＝清空垃圾桶。"""
    removed = []
    with _trash_lock:
        trash = _load_trash()
        for tid in list(trash) if ids is None else dict.fromkeys(ids):
            if tid not in trash or not _NAME_RE.match(tid):
                continue
            with contextlib.suppress(FileNotFoundError):
                (IMAGE_TRASH_DIR / tid).unlink()
            trash.pop(tid)
            _drop_thumbs("trash", tid)
            removed.append(tid)
        _save_trash(trash)
    return {"purged": removed}
