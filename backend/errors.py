"""把後端例外整理成使用者看得懂的一句話。

httpx 的逾時例外 str() 是空字串，直接塞進「分鏡生成失敗：{e}」會變成冒號後面空白；
連線失敗、Ollama / A1111 回錯誤碼時也常只剩一串 URL。這裡統一翻成有用的訊息。
"""
from __future__ import annotations

import httpx

from config import HTTP_TIMEOUT


def _origin(url: httpx.URL | None) -> str:
    if not url:
        return ""
    port = f":{url.port}" if url.port else ""
    return f"{url.scheme}://{url.host}{port}"


def _req_origin(e: BaseException) -> str:
    # httpx 例外若沒綁 request，存取 .request 會直接丟 RuntimeError
    try:
        return _origin(e.request.url)  # type: ignore[attr-defined]
    except Exception:
        return ""


def describe(e: BaseException) -> str:
    if isinstance(e, httpx.TimeoutException):
        origin = _req_origin(e)
        head = f"等待 {origin} 回應逾時" if origin else "等待回應逾時"
        return (
            f"{head}（超過 {HTTP_TIMEOUT:g} 秒）。模型可能正忙、正在載入或太慢，"
            "請稍後再試，或用環境變數 HTTP_TIMEOUT 調高上限。"
        )
    if isinstance(e, httpx.ConnectError):
        origin = _req_origin(e)
        return f"無法連線到 {origin}" if origin else "無法連線到後端服務"
    if isinstance(e, httpx.HTTPStatusError):
        r = e.response
        body = ""
        try:
            data = r.json()
            body = data.get("error") or data.get("detail") or "" if isinstance(data, dict) else ""
        except ValueError:
            body = r.text[:200]
        return f"{_req_origin(e)} 回應 HTTP {r.status_code}".strip() + (f"：{body}" if body else "")
    text = str(e).strip()
    return text or type(e).__name__
