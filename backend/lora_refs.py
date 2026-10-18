"""webui 自己存的資料裡寫到的 LoRA 名稱（目前是漫畫工作室的作品：角色卡 LoRA、畫風、各格提示詞…）。

LoRA 改名（Civitai Helper 的 civitai_rename_model / civitai_fix_names，或在 Forge 改）之後，
作品裡的 <lora:舊名:…> 就找不到模型了：
- replace(mapping)：把 <lora:舊名:…> 換成 <lora:新名:…>（改名的工具成功後自動做，LoRA 管理也能手動做）
- missing(names, aliases)：作品裡用到、但目前沒有這個 LoRA 的名稱，附上建議的替換
  （去掉 / 加上 _2 這類尾碼、或別名相同的 LoRA）

作品的分鏡版本（快照）是歷史紀錄，不改；聊天紀錄、提示詞歷史也不改。
"""
from __future__ import annotations

import re
from typing import Any

import comics_store

_TAG_RE = re.compile(r"<(lora|lyco):([^:>]+)(?=[:>])", re.IGNORECASE)
_SUFFIX_RE = re.compile(r"^(.+)_\d{1,3}$")


def rename_in_text(text: str, mapping: dict[str, str]) -> str:
    """'<lora:old:0.8>' → '<lora:new:0.8>'（名稱完全相同才換，大小寫照原樣比對）。"""
    if not text or "<" not in text:
        return text
    return _TAG_RE.sub(lambda m: f"<{m.group(1)}:{mapping.get(m.group(2).strip(), m.group(2))}", text)


def _walk(obj: Any, fn) -> Any:
    if isinstance(obj, str):
        return fn(obj)
    if isinstance(obj, list):
        return [_walk(x, fn) for x in obj]
    if isinstance(obj, dict):
        return {k: _walk(v, fn) for k, v in obj.items()}
    return obj


def _names_in(obj: Any, out: dict[str, int]) -> None:
    if isinstance(obj, str):
        for m in _TAG_RE.finditer(obj):
            name = m.group(2).strip()
            out[name] = out.get(name, 0) + 1
    elif isinstance(obj, list):
        for x in obj:
            _names_in(x, out)
    elif isinstance(obj, dict):
        for v in obj.values():
            _names_in(v, out)


def _projects() -> list[dict[str, Any]]:
    out = []
    for s in comics_store.list_summaries():
        data = comics_store.get(s["id"]) if s.get("id") else None
        if isinstance(data, dict):
            out.append(data)
    return out


def replace(mapping: dict[str, str]) -> list[dict[str, Any]]:
    """把所有漫畫作品裡的 <lora:舊名:…> 換成新名。回 [{"id", "title", "count"}]（有改到的作品）。"""
    mapping = {str(k).strip(): str(v).strip() for k, v in (mapping or {}).items()
               if str(k).strip() and str(v).strip() and str(k).strip() != str(v).strip()}
    if not mapping:
        return []
    changed = []
    for data in _projects():
        before: dict[str, int] = {}
        _names_in(data, before)
        count = sum(n for name, n in before.items() if name in mapping)
        if not count:
            continue
        comics_store.upsert(_walk(data, lambda s: rename_in_text(s, mapping)))
        changed.append({"id": data.get("id"), "title": data.get("title") or "", "count": count})
    return changed


def missing(names: set[str], aliases: dict[str, str]) -> list[dict[str, Any]]:
    """作品裡用到、但目前沒有的 LoRA 名稱。names＝現有的 LoRA 名稱；aliases＝{別名: 名稱}。
    每筆 {"name", "projects": [{"id", "title", "count"}], "suggestion", "candidates"}。"""
    lowered = {n.lower(): n for n in names}
    used: dict[str, list[dict[str, Any]]] = {}
    for data in _projects():
        found: dict[str, int] = {}
        _names_in(data, found)
        for name, n in found.items():
            if name in names:
                continue
            used.setdefault(name, []).append({"id": data.get("id"), "title": data.get("title") or "", "count": n})
    out = []
    for name, projects in sorted(used.items()):
        candidates: list[str] = []
        if name in aliases and aliases[name] in names:
            candidates.append(aliases[name])          # 別名就是這個名字的 LoRA（例如改名前的 xxx_2 的別名 xxx）
        hit = _SUFFIX_RE.match(name)
        if hit and hit.group(1) in names:
            candidates.append(hit.group(1))            # xxx_2 → xxx（_2 改回原名之後）
        candidates += sorted(n for n in names if _SUFFIX_RE.match(n) and _SUFFIX_RE.match(n).group(1) == name)
        if name.lower() in lowered:
            candidates.append(lowered[name.lower()])   # 只差大小寫
        candidates = list(dict.fromkeys(c for c in candidates if c != name))
        out.append({"name": name, "projects": projects, "candidates": candidates,
                    "suggestion": candidates[0] if len(candidates) == 1 else None})
    return out


def mapping_from_result(tool: str, data: Any) -> dict[str, str]:
    """Civitai Helper 改名類工具的結果 → {舊名: 新名}（LoRA 才算；名稱是檔名去掉副檔名）。"""
    if not isinstance(data, dict):
        return {}
    if tool == "civitai_rename_model" and data.get("type") == "lora":
        old, new = _stem(data.get("old_name")), _stem(data.get("new_name"))
        return {old: new} if old and new and old != new else {}
    if tool == "civitai_fix_names":
        lora = {r.get("stem") for r in data.get("results") or [] if isinstance(r, dict) and r.get("type") == "lora"}
        return {k: v for k, v in (data.get("mapping") or {}).items() if k in lora and k != v}
    return {}


def _stem(rel: Any) -> str:
    name = str(rel or "").replace("\\", "/").rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0] if "." in name else name
