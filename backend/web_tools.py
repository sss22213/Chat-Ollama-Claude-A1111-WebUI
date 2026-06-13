"""Web 搜尋與網頁抓取（給模型上網用）。

- web_search：DuckDuckGo（預設，免 key）或 SearXNG。
- fetch_url：抓網頁正文（BeautifulSoup 去雜訊），含基本 SSRF 防護。
provider 設定來自 settings_store。
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

import settings_store

UA = "Mozilla/5.0 (compatible; LocalChatBot/1.0)"


# ---- 搜尋 ----
async def web_search(query: str, max_results: int | None = None) -> list[dict]:
    cfg = settings_store.get_web()
    n = int(max_results or cfg.get("max_results") or 5)
    provider = cfg.get("provider", "duckduckgo")
    if provider == "searxng" and cfg.get("searxng_url"):
        return await _searxng(cfg["searxng_url"], query, n)
    return await _duckduckgo(query, n)


async def _duckduckgo(query: str, n: int) -> list[dict]:
    def _run():
        from ddgs import DDGS

        out = []
        for r in DDGS().text(query, max_results=n):
            out.append(
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", "") or r.get("url", ""),
                    "snippet": r.get("body", "") or r.get("snippet", ""),
                }
            )
        return out

    return await asyncio.to_thread(_run)


async def _searxng(base: str, query: str, n: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": UA}) as client:
        resp = await client.get(
            f"{base.rstrip('/')}/search",
            params={"q": query, "format": "json"},
        )
        resp.raise_for_status()
        data = resp.json()
    out = []
    for r in (data.get("results") or [])[:n]:
        out.append(
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
            }
        )
    return out


# ---- 抓網頁 ----
def _is_blocked_host(host: str) -> bool:
    """擋掉 loopback / 私網 / link-local，避免模型打到本機內部服務。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return True
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if (
            addr.is_loopback
            or addr.is_private
            or addr.is_link_local
            or addr.is_reserved
        ):
            return True
    return False


async def fetch_url(url: str, max_chars: int | None = None) -> dict:
    cfg = settings_store.get_web()
    limit = int(max_chars or cfg.get("fetch_max_chars") or 6000)

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("只允許 http/https 網址")
    if _is_blocked_host(parsed.hostname):
        raise ValueError("基於安全，拒絕存取內部/私有位址")

    async with httpx.AsyncClient(
        timeout=20, follow_redirects=True, headers={"User-Agent": UA}
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "")
        if "html" not in ctype and "text" not in ctype:
            raise ValueError(f"不支援的內容類型：{ctype or '未知'}")
        html = resp.text

    soup = BeautifulSoup(html, "lxml")
    title = (soup.title.string if soup.title else "") or ""
    for tag in soup(
        ["script", "style", "nav", "footer", "header", "noscript", "aside", "form"]
    ):
        tag.decompose()
    text = " ".join(soup.get_text(" ").split())
    truncated = len(text) > limit
    return {
        "url": str(resp.url),
        "title": title.strip(),
        "text": text[:limit],
        "truncated": truncated,
    }
