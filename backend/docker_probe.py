"""Best-effort 列出 docker 容器（透過 unix socket 直接打 docker API，免額外套件）。

主機上若使用者不在 docker 群組會 permission denied → 回傳 available=False。
docker 部署時把 /var/run/docker.sock 掛進後端容器即可使用。
"""
from __future__ import annotations

import os
from typing import Any

import httpx

DOCKER_SOCK = os.getenv("DOCKER_SOCK", "/var/run/docker.sock")


async def list_containers() -> list[dict[str, Any]]:
    transport = httpx.AsyncHTTPTransport(uds=DOCKER_SOCK)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://docker", timeout=5
    ) as client:
        resp = await client.get("/containers/json")
        resp.raise_for_status()
        data = resp.json()

    out: list[dict[str, Any]] = []
    for c in data:
        names = [n.lstrip("/") for n in c.get("Names", [])]
        ports = []
        seen = set()
        for p in c.get("Ports", []):
            priv = p.get("PrivatePort")
            key = (priv, p.get("PublicPort"))
            if priv is None or key in seen:
                continue
            seen.add(key)
            ports.append(
                {
                    "private": priv,
                    "public": p.get("PublicPort"),
                    "type": p.get("Type"),
                }
            )
        networks = list((c.get("NetworkSettings") or {}).get("Networks", {}).keys())
        out.append(
            {
                "name": names[0] if names else c.get("Id", "")[:12],
                "names": names,
                "image": c.get("Image"),
                "ports": ports,
                "networks": networks,
            }
        )
    return out
