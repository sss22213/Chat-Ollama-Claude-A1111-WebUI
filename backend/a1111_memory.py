"""A1111 記憶體管理技能的結果整理：/sdapi/v1/memory 的原始位元組數 → 模型看得懂的幾行 GB。

由 skill_tools 的 postprocess "a1111_memory"（查詢）與 "a1111_memory_after"
（卸載 / 載回之後再查一次，回報前後狀態）呼叫。
"""
from __future__ import annotations

from typing import Any

import httpx

_GB = 1024**3


def _gb(v: Any) -> str:
    try:
        return f"{float(v) / _GB:.1f} GB"
    except (TypeError, ValueError):
        return "?"


def _num(d: Any, *keys: str) -> float:
    for k in keys:
        if not isinstance(d, dict):
            return 0.0
        d = d.get(k)
    try:
        return float(d or 0)
    except (TypeError, ValueError):
        return 0.0


def summary(data: Any) -> str:
    """把 /sdapi/v1/memory 整理成幾行。"""
    if not isinstance(data, dict):
        return f"Unexpected /sdapi/v1/memory response: {str(data)[:300]}"
    ram, cuda = data.get("ram") or {}, data.get("cuda") or {}
    lines = [
        f"System RAM: {_gb(ram.get('used'))} used by A1111 / {_gb(ram.get('free'))} free / {_gb(ram.get('total'))} total",
    ]
    if isinstance(cuda, dict) and cuda.get("system"):
        sysm = cuda["system"]
        alloc = _num(cuda, "allocated", "current")
        lines += [
            f"GPU {cuda.get('device') or ''} (whole card, all programs incl. Ollama / sd.cpp): "
            f"{_gb(sysm.get('used'))} used / {_gb(sysm.get('free'))} free / {_gb(sysm.get('total'))} total",
            f"A1111's own VRAM: {_gb(alloc)} allocated now (peak {_gb(_num(cuda, 'allocated', 'peak'))}), "
            f"{_gb(_num(cuda, 'reserved', 'current'))} reserved",
            "Checkpoint in VRAM: " + ("yes (weights are on the GPU)" if alloc > 0.5 * _GB else "no (A1111 holds almost no VRAM; the model is unloaded or in RAM)"),
            f"Out-of-memory events since start: {int(_num(cuda, 'events', 'oom'))}",
        ]
    else:
        lines.append(f"GPU: not reported ({cuda.get('error') if isinstance(cuda, dict) else cuda})")
    return "\n".join(lines)


async def after_action(tool: dict[str, Any], base: str, data: Any) -> str:
    """卸載 / 載回完成後，再查一次記憶體，讓模型能回報結果。"""
    head = f"{tool['name']} done" + (f" (response: {str(data)[:200]})" if data not in (None, "", {}, []) else "") + "."
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            mem = (await client.get(base.rstrip("/") + "/sdapi/v1/memory")).json()
        return head + "\nMemory now:\n" + summary(mem)
    except (httpx.HTTPError, ValueError) as e:
        return head + f" (could not read memory afterwards: {e})"
