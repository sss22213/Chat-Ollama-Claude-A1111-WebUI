"""技能工具：讓一個技能（SKILL.md 旁的 tools.json、或 scripts/ 內的 Python 腳本）
成為模型可呼叫的工具，由後端代為執行、把結果回給模型。

兩類工具：

1. HTTP API 工具（tools.json，kind 省略或 "http"）——後端代發 HTTP 請求。
2. 腳本工具——後端以 sys.executable 執行技能資料夾內的 *.py（設定頁
   「允許技能執行腳本」開啟後才有；預設關閉）。
   a. 通用 run_skill_script(skill?, script, args[])：技能只要有 scripts/ 就自動掛上，
      模型照 SKILL.md 寫的指令行填 script 與 args 即可（社群技能免改）。
   b. tools.json 宣告的固定腳本工具（kind: "script"）：把參數對應成命令列 flag，
      模型只看到 function schema、argv 由後端組。

tools.json 格式（放在技能資料夾內，與 SKILL.md 同層；只能由檔案系統放入，
網頁的技能編輯器不會寫它）：

{
  "base_url": "{a1111_url}/civitai-helper/v1",   # 可用的佔位符：{a1111_url} {ollama_url}
  "tools": [
    {
      "name": "civitai_list_local_models",          # 工具名（模型看到的 function name）
      "description": "…",                            # 給模型看的說明
      "method": "GET",                               # GET | POST | PUT | DELETE
      "path": "/models",                             # 接在 base_url 後；可含 {param} 佔位符
      "parameters": { "type": "object", "properties": {…}, "required": […] },
      "timeout": 120,                                # 選用，秒
      "max_chars": 6000,                             # 選用，回傳給模型的字元上限
      "result_note": "…",                            # 選用，附在結果後面提示模型怎麼用
      "attach_image": {"field": "ref_images", "as": "list"},   # 選用：把使用者最後附的圖（data URL）放進 body
      "query_params": ["full"],                      # 選用：POST/PUT 時這些參數改放網址查詢字串
      "postprocess": "sdcpp_job"                     # 選用：後端接手輪詢工作、存圖、推 image 事件
    },
    {
      "name": "civitai_search",                      # 固定腳本工具
      "kind": "script",
      "description": "…",
      "script": "civitai.py",                        # 技能資料夾內的 *.py（相對路徑）
      "argv": ["models"],                            # 固定接在腳本後的參數
      "flags": { "query": "--query", "nsfw": "--nsfw" },   # 參數 → flag；未列者用 --<name>
      "positional": ["model_id"],                    # 依序當位置參數（不加 flag）
      "parameters": { "type": "object", "properties": {…} },
      "postprocess": "civitai_models",           # 選用：後端把原始輸出整理成摘要＋前端事件
      "timeout": 120, "max_chars": 8000, "result_note": "…"
    }
  ]
}

呼叫時：HTTP 工具的 path 內 {param} 先用同名參數替換（並從參數移除），其餘參數
GET/DELETE 走 query string、POST/PUT 走 JSON body。回應若是 JSON 就美化後
截斷回給模型，否則回純文字。
腳本工具：布林 true → 只加 flag；陣列 → flag + 逗號串接；None → 略過。

腳本執行環境（run_script）：
- 直譯器＝後端自己的 Python（sys.executable），不經 shell，argv 逐項傳入。
- 腳本檔必須位於該技能資料夾內且為 *.py（模型給的路徑會先正規化：去掉
  `python`、`./`、`.\\skills\\<slug>\\` 之類前綴，找不到再到 scripts/ 內找）。
- cwd＝DATA_DIR/skill-work/<slug>/（持久、docker 下在 volume 內），腳本寫的檔案留在那裡。
- 環境變數只給最小集合（PATH、HOME=工作目錄、PYTHONPATH=技能目錄、proxy），
  加上 config.SKILL_SCRIPT_ENV 列出的透傳變數與工作目錄內 .env 的內容；
  這些值在輸出中會被遮罩成 ***（避免 token 印給模型／使用者）。
- 逾時（config.SKILL_SCRIPT_TIMEOUT）直接 kill；stdout/stderr 各自截斷後回給模型。

引擎支援：
- ollama：直接作為 function calling 的 tools（chat.py 併入 tool_schema）。
- claude_cli：以 [[CALL]]{"tool": "...", "args": {...}}[[/CALL]] 指令標記呼叫，
  後端執行後把結果當下一輪輸入再跑一次（見 chat._run_cli_engine）。
- codex：目前走固定的結構化輸出 schema，尚不支援技能工具。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any

import httpx

import settings_store
from config import DATA_DIR, HTTP_TIMEOUT, OLLAMA_URL, SDCPP_URL, SKILL_SCRIPT_ENV, SKILL_SCRIPT_TIMEOUT

log = logging.getLogger("skill_tools")

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DEFAULT_MAX_CHARS = 6000
_DEFAULT_TIMEOUT = 120.0
_SCRIPT_MAX_CHARS = 8000
_STDERR_MAX_CHARS = 2000

# 通用腳本工具名（模型看到的 function name）
SCRIPT_TOOL = "run_skill_script"
_SKIP_DIRS = {"__pycache__", "node_modules", "venv", ".venv", "tests", "test"}


def normalize(raw: dict[str, Any], slug: str) -> list[dict[str, Any]]:
    """把 tools.json 內容整理成工具定義清單；不合法的項目直接略過。"""
    if not isinstance(raw, dict):
        return []
    base_url = str(raw.get("base_url") or "").strip()
    out: list[dict[str, Any]] = []
    for t in raw.get("tools") or []:
        if not isinstance(t, dict):
            continue
        name = str(t.get("name") or "").strip()
        if not _NAME_RE.match(name) or name == SCRIPT_TOOL:
            continue
        kind = str(t.get("kind") or "http").strip().lower()
        params = t.get("parameters")
        if not isinstance(params, dict) or params.get("type") != "object":
            params = {"type": "object", "properties": {}}
        params.setdefault("properties", {})
        defaults = t.get("defaults")
        if not isinstance(defaults, dict):
            defaults = {}
        common = {
            "name": name,
            "skill": slug,
            "kind": kind,
            "description": str(t.get("description") or "").strip(),
            "parameters": params,
            # 固定附加的參數（模型看不到、也蓋不掉模型明確給的值），例如 wait/timeout
            "defaults": defaults,
            "result_note": str(t.get("result_note") or "").strip(),
        }
        if kind == "script":
            script = str(t.get("script") or "").strip()
            if not script:
                continue
            flags = t.get("flags")
            out.append(
                {
                    **common,
                    "script": script,
                    "argv": [str(a) for a in (t.get("argv") or [])],
                    "flags": {str(k): str(v) for k, v in (flags or {}).items()}
                    if isinstance(flags, dict)
                    else {},
                    "positional": [str(p) for p in (t.get("positional") or [])],
                    "postprocess": str(t.get("postprocess") or "").strip(),
                    "timeout": float(t.get("timeout") or SKILL_SCRIPT_TIMEOUT),
                    "max_chars": int(t.get("max_chars") or _SCRIPT_MAX_CHARS),
                }
            )
            continue
        if kind != "http":
            continue
        path = str(t.get("path") or "").strip()
        if not path:
            continue
        method = str(t.get("method") or "GET").upper()
        if method not in ("GET", "POST", "PUT", "DELETE"):
            continue
        out.append(
            {
                **common,
                "method": method,
                "base_url": str(t.get("base_url") or base_url).strip(),
                "path": path,
                # 把對話中最後附上的圖片塞進 body：{"field": "ref_images", "as": "list"|"single"}
                "attach_image": t.get("attach_image") if isinstance(t.get("attach_image"), dict) else None,
                # POST/PUT 時仍放在網址查詢字串的參數名（例如 A1111 的 ?full=true）
                "query_params": [str(q) for q in (t.get("query_params") or []) if isinstance(q, str)],
                "postprocess": str(t.get("postprocess") or "").strip(),
                "vision_max": int(t.get("vision_max") or 0),
                "timeout": float(t.get("timeout") or _DEFAULT_TIMEOUT),
                "max_chars": int(t.get("max_chars") or _DEFAULT_MAX_CHARS),
            }
        )
    return out


def ollama_schema(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """轉成 ollama / OpenAI 風格的 function tool schema。"""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        }
        for t in tools
    ]


def directive_instructions(tools: list[dict[str, Any]]) -> str:
    """給 CLI 引擎（Claude）的 system 指示：如何用 [[CALL]] 標記呼叫技能工具。"""
    if not tools:
        return ""
    lines = [
        "",
        "# Skill API tools (IMPORTANT)",
        "The active skill provides API tools. You call a tool by printing this marker "
        "on its own line (the app intercepts it, performs the HTTP call, and then sends "
        "you the result as the next message so you can continue):",
        '[[CALL]]{"tool": "<tool name>", "args": {<arguments as JSON>}}[[/CALL]]',
        "Rules: emit at most ONE [[CALL]] marker per reply and STOP right after it — the "
        "result comes back in the next turn. Never wrap the marker in code fences, never "
        "invent results, and never claim you cannot call tools. When you have the result, "
        "answer the user in their language. Do not print raw JSON to the user unless asked.",
        "Available tools:",
    ]
    for t in tools:
        props = t["parameters"].get("properties") or {}
        required = set(t["parameters"].get("required") or [])
        arg_desc = ", ".join(
            f"{k}{'*' if k in required else ''}: {(v or {}).get('type', 'any')}"
            + (f" — {(v or {}).get('description')}" if (v or {}).get("description") else "")
            for k, v in props.items()
        )
        lines.append(f"- {t['name']}: {t['description']}" + (f" Args: {arg_desc}" if arg_desc else ""))
    lines.append("(* = required argument)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 腳本工具
# ---------------------------------------------------------------------------
def list_scripts(skill_dir: Path) -> list[str]:
    """技能資料夾內可執行的 Python 腳本（相對技能資料夾的 posix 路徑）。

    略過隱藏目錄、__pycache__、venv、tests 與 __init__.py。"""
    out: list[str] = []
    try:
        root = skill_dir.resolve()
        for p in sorted(skill_dir.rglob("*.py")):
            try:
                rel = p.relative_to(skill_dir)
                if not p.is_file() or root not in p.resolve().parents:
                    continue
            except (OSError, ValueError):
                continue
            parts = rel.parts
            if any(x.startswith(".") or x in _SKIP_DIRS for x in parts[:-1]):
                continue
            if p.name == "__init__.py" or p.name.startswith("."):
                continue
            out.append(rel.as_posix())
    except OSError:
        pass
    return out


def runner_tool(skills: list[dict[str, Any]]) -> dict[str, Any] | None:
    """通用「執行技能腳本」工具定義。skills=[{"slug": …, "scripts": […]}]；都沒腳本回 None。"""
    skills = [s for s in skills if s.get("scripts")]
    if not skills:
        return None
    single = len(skills) == 1
    listing = "; ".join(f"skill '{s['slug']}': {', '.join(s['scripts'])}" for s in skills)
    desc = (
        "Run a Python script bundled with the active skill on the app server and get its "
        "stdout/stderr back. Use it whenever the skill's instructions say to run a script: "
        "e.g. `python ./scripts/foo.py models --query \"x y\" --limit 5` becomes "
        "script='foo.py', args=['models','--query','x y','--limit','5'] (one list item per "
        "argument, no shell quoting). Available scripts — " + listing + "."
    )
    props: dict[str, Any] = {
        "script": {
            "type": "string",
            "description": "Script file inside the skill folder, e.g. 'civitai.py' or 'scripts/civitai.py'.",
        },
        "args": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Command-line arguments as separate strings, in order.",
        },
    }
    required = ["script"]
    if not single:
        props = {
            "skill": {
                "type": "string",
                "enum": [s["slug"] for s in skills],
                "description": "Which skill's script to run.",
            },
            **props,
        }
        required = ["skill", "script"]
    return {
        "name": SCRIPT_TOOL,
        "skill": skills[0]["slug"] if single else "",
        "kind": "runner",
        "description": desc,
        "parameters": {"type": "object", "properties": props, "required": required},
        "defaults": {},
        "timeout": SKILL_SCRIPT_TIMEOUT,
        "max_chars": _SCRIPT_MAX_CHARS,
        "result_note": "",
        "skills": {s["slug"]: list(s["scripts"]) for s in skills},
    }


def is_script_tool(tool: dict[str, Any]) -> bool:
    return (tool.get("kind") or "http") in ("script", "runner")


def skill_dir(slug: str) -> Path | None:
    """技能資料夾（解析後仍須在技能根目錄內）；不存在回 None。"""
    try:
        base = settings_store.get_skills_dir().resolve()
        d = (base / slug).resolve()
    except (OSError, RuntimeError):
        return None
    if d == base or base not in d.parents or not d.is_dir():
        return None
    return d


def workdir_for(slug: str) -> Path:
    """腳本的工作目錄（持久）；不存在就建立。"""
    d = DATA_DIR / "skill-work" / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


_PY_PREFIX_RE = re.compile(r"^(?:python3?(?:\.exe)?|py)\s+", re.I)


def resolve_script(sdir: Path, script: str, slug: str) -> Path | None:
    """把模型給的腳本路徑對應到技能資料夾內的 *.py；找不到或跑出資料夾回 None。"""
    s = (script or "").strip().strip("'\"`")
    s = _PY_PREFIX_RE.sub("", s).strip().replace("\\", "/")
    if not s:
        return None
    root = sdir.resolve()
    cands: list[Path] = []
    if s.startswith("/") or re.match(r"^[A-Za-z]:/", s):
        cands.append(Path(s))
        # 絕對路徑但其實指在技能資料夾內（例如模型照著容器路徑寫）
        marker = f"/{slug}/"
        if marker in s:
            s = s.split(marker, 1)[1]
        else:
            s = ""
    s = re.sub(r"^(\./)+", "", s)
    for pre in (f"skills/{slug}/", f"{slug}/"):
        if s.startswith(pre):
            s = s[len(pre):]
    s = s.lstrip("/")
    if s and ".." not in s.split("/"):
        cands += [sdir / s, sdir / "scripts" / s]
        if "/" not in s:
            try:
                cands += sorted(sdir.rglob(s))
            except OSError:
                pass
    for c in cands:
        try:
            r = c.resolve()
        except (OSError, RuntimeError):
            continue
        if root in r.parents and r.is_file() and r.suffix == ".py":
            return r
    return None


def _read_env_file(p: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.lower().startswith("export "):
            line = line[7:].lstrip()
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        if _ENV_KEY_RE.match(k):
            out[k] = v
    return out


_PASSTHROUGH_ALWAYS = (
    "http_proxy", "https_proxy", "no_proxy", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "TZ",
)


def script_env(sdir: Path, workdir: Path) -> tuple[dict[str, str], list[str]]:
    """腳本的最小環境；回 (env, 要在輸出中遮罩的祕密值)。"""
    env = {
        "PATH": os.environ.get("PATH") or "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(workdir),  # 不給真正的家目錄（容器內掛著 ~/.claude、~/.codex）
        "LANG": os.environ.get("LANG") or "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join([str(sdir), str(sdir / "scripts")]),
        "SKILL_DIR": str(sdir),
        "SKILL_WORKDIR": str(workdir),
    }
    for k in _PASSTHROUGH_ALWAYS:
        if os.environ.get(k):
            env[k] = os.environ[k]
    secrets: list[str] = []
    for k in SKILL_SCRIPT_ENV:
        v = os.environ.get(k)
        if v:
            env[k] = v
            secrets.append(v)
    for k, v in _read_env_file(workdir / ".env").items():
        env[k] = v
        secrets.append(v)
    return env, [s for s in secrets if len(s) >= 6]


def _redact(text: str, secrets: list[str]) -> str:
    for s in secrets:
        text = text.replace(s, "***")
    return text


async def run_script(
    slug: str,
    script: str,
    args: list[str],
    *,
    timeout: float | None = None,
    max_chars: int = _SCRIPT_MAX_CHARS,
    raw: bool = False,
) -> str | tuple[str, str, int]:
    """執行技能內的一支 Python 腳本，回傳要給模型看的文字（成功或失敗都以文字說明）。

    raw=True 時，腳本真的跑起來後改回 (stdout, stderr, returncode) 給 postprocess 用；
    找不到腳本等前置錯誤仍回字串。"""
    sdir = skill_dir(slug)
    if not sdir:
        return f"Script run failed: unknown skill '{slug}'."
    target = resolve_script(sdir, script, slug)
    if not target:
        avail = ", ".join(list_scripts(sdir)) or "(none)"
        return (
            f"Script run failed: '{script}' is not a Python script inside skill '{slug}'. "
            f"Available scripts: {avail}."
        )
    argv = [str(a) for a in (args or [])]
    workdir = workdir_for(slug)
    env, secrets = script_env(sdir, workdir)
    shown = shlex.join([target.relative_to(sdir).as_posix(), *argv])
    limit = float(timeout or SKILL_SCRIPT_TIMEOUT)
    limit = max(1.0, min(limit, SKILL_SCRIPT_TIMEOUT))
    log.info("skill script [%s]: %s", slug, shown)
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(target),
            *argv,
            cwd=str(workdir),
            env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as e:
        return f"Script run failed: could not start `{shown}` ({e})"
    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=limit)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        with contextlib.suppress(Exception):
            await proc.wait()
        return f"Script run failed: `{shown}` timed out after {limit:.0f}s and was killed."
    out = _redact(out_b.decode("utf-8", "replace"), secrets).strip()
    err = _redact(err_b.decode("utf-8", "replace"), secrets).strip()
    if raw:
        return out[:max_chars], err, int(proc.returncode or 0)
    text = f"Result of `{shown}` (exit code {proc.returncode}):\n" + _truncate(
        out or "(no stdout)", max_chars
    )
    if err:
        text += "\n\n[stderr]\n" + _truncate(err, min(_STDERR_MAX_CHARS, max_chars))
    return text


def script_argv(tool: dict[str, Any], args: dict[str, Any]) -> list[str]:
    """tools.json 宣告的固定腳本工具：把參數組成命令列。"""
    argv = list(tool.get("argv") or [])
    flags = tool.get("flags") or {}
    positional = tool.get("positional") or []
    used: set[str] = set()
    for p in positional:
        v = args.get(p)
        if v is not None and v != "":
            argv.append(",".join(str(x) for x in v) if isinstance(v, list) else str(v))
            used.add(p)
    for k, v in args.items():
        if k in used or v is None:
            continue
        flag = flags.get(k, "--" + k.replace("_", "-"))
        if not flag:
            continue
        if isinstance(v, bool):
            if v:
                argv.append(flag)
        elif isinstance(v, list):
            argv += [flag, ",".join(str(x) for x in v)]
        else:
            argv += [flag, str(v)]
    return argv


def _runner_args(raw: Any) -> list[str]:
    """run_skill_script 的 args：接受陣列、JSON 陣列字串、或一整行命令列字串。"""
    if raw is None or raw == "":
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    s = str(raw).strip()
    if s.startswith("["):
        try:
            v = json.loads(s)
            if isinstance(v, list):
                return [str(x) for x in v]
        except json.JSONDecodeError:
            pass
    try:
        return shlex.split(s)
    except ValueError:
        return s.split()


def _resolve_base(url: str) -> str:
    return (
        url.replace("{a1111_url}", settings_store.get_a1111_url().rstrip("/"))
        .replace("{ollama_url}", OLLAMA_URL.rstrip("/"))
        .replace("{sdcpp_url}", SDCPP_URL)
        .rstrip("/")
    )


def _coerce(args: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """依 schema 把模型給的字串轉成正確型別（本地模型常把數字/布林寫成字串）。"""
    props = params.get("properties") or {}
    out: dict[str, Any] = {}
    for k, v in (args or {}).items():
        spec = props.get(k) or {}
        typ = spec.get("type")
        try:
            if typ == "integer" and isinstance(v, str) and v.strip():
                v = int(float(v))
            elif typ == "number" and isinstance(v, str) and v.strip():
                v = float(v)
            elif typ == "boolean" and isinstance(v, str):
                v = v.strip().lower() in ("1", "true", "yes", "y", "on")
            elif typ == "array" and isinstance(v, str):
                s = v.strip()
                if s.startswith("["):
                    v = json.loads(s)
                else:
                    v = [p.strip() for p in s.split(",") if p.strip()]
        except (ValueError, json.JSONDecodeError):
            pass
        out[k] = v
    return out


_A1111_THUMB_RE = re.compile(r"(?:\.?/)?sd_extra_networks/thumb\?")


def rewrite_a1111_thumbs(text: str) -> str:
    """A1111 回傳的相對圖片網址（./sd_extra_networks/thumb?filename=…，例如 Civitai Helper
    的 local_url）→ 本 app 的代理 /api/a1111-thumb?filename=…，模型拿去嵌圖才顯示得出來。"""
    return _A1111_THUMB_RE.sub("/api/a1111-thumb?", text) if "sd_extra_networks/thumb?" in text else text


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + f"\n…(truncated, {len(text) - limit} more chars)"


class ToolOutput:
    """工具執行結果：text 給模型；events 是要順便推給前端的 SSE 事件（如候選卡片）。"""

    __slots__ = ("text", "events", "vision", "vision_labels")

    def __init__(self, text: str, events: list[dict[str, Any]] | None = None):
        self.text = text
        # "_vision" 事件不送前端：是要附在工具訊息上給視覺模型看的圖（base64）
        self.vision: list[str] = []
        self.vision_labels: list[str] = []
        self.events = []
        for ev in events or []:
            if ev.get("type") == "_vision":
                self.vision += list(ev.get("images") or [])
                self.vision_labels += list(ev.get("labels") or [])
            else:
                self.events.append(ev)

    def __str__(self) -> str:
        return self.text


async def _postprocess(name: str, stdout: str) -> tuple[str, list[dict[str, Any]]]:
    """tools.json 的 "postprocess"：把腳本原始輸出換成結構化摘要＋前端事件。"""
    if name == "civitai_models":
        import civitai_cards

        return await civitai_cards.process(stdout)
    return stdout, []


async def _postprocess_http(name: str, tool: dict[str, Any], base: str, data: Any) -> tuple[str, list[dict[str, Any]]]:
    """HTTP 工具的 postprocess：拿到回應 JSON 後由後端接手（如 sd.cpp 的非同步工作）。"""
    if name == "sdcpp_job":
        import sdcpp_jobs

        return await sdcpp_jobs.process(tool, base, data)
    if name == "sdcpp_caps":
        import sdcpp_jobs

        return sdcpp_jobs.caps_summary(data), []
    if name == "civitai_examples":
        import civitai_examples

        return await civitai_examples.process(tool, base, data)
    if name == "a1111_memory":
        import a1111_memory

        return a1111_memory.summary(data), []
    if name == "a1111_memory_after":
        import a1111_memory

        return await a1111_memory.after_action(tool, base, data), []
    return json.dumps(data, ensure_ascii=False, indent=1), []


async def call(tool: dict[str, Any], args: dict[str, Any] | None, image: str | None = None) -> str:
    """執行一個技能工具，回傳要給模型看的文字（成功或失敗都以文字說明）。"""
    return (await call_full(tool, args, image=image)).text


def _image_size(image: str, max_pixels: int, multiple: int) -> tuple[int, int] | None:
    """附圖的輸出尺寸：保持長寬比、面積不超過 max_pixels、邊長取 multiple 的倍數（至少 256）。"""
    import base64
    import io
    import math

    try:
        from PIL import Image

        raw = base64.b64decode(image.split(",", 1)[1] if image.startswith("data:") else image)
        w, h = Image.open(io.BytesIO(raw)).size
    except Exception:  # noqa: BLE001 — 讀不到尺寸就交給伺服器預設
        return None
    scale = min(1.0, math.sqrt(max_pixels / float(w * h)))
    if min(w, h) * scale < 256:  # 太小的圖等比放大到短邊 256
        scale = 256 / float(min(w, h))
    fit = lambda v: max(multiple, int(round(v * scale / multiple)) * multiple)  # noqa: E731
    return fit(w), fit(h)


def _as_data_url(image: str) -> str:
    return image if image.startswith("data:") else f"data:image/png;base64,{image}"


async def call_full(
    tool: dict[str, Any], args: dict[str, Any] | None, image: str | None = None
) -> ToolOutput:
    """同 call，但連同要推給前端的事件一起回（chat.py 用）。image＝對話中最後附的圖（base64 或 data URL）。"""
    raw_in = dict(args or {})
    kind = tool.get("kind") or "http"

    # --- 腳本工具（通用 runner / tools.json 宣告） ---
    if kind in ("runner", "script"):
        if not settings_store.get_skill_scripts():
            return ToolOutput(
                f"Tool {tool['name']} is disabled: skill scripts are turned off in Settings "
                "(Skills → Allow skills to run scripts)."
            )
        if kind == "runner":
            allowed = tool.get("skills") or {}
            slug = str(raw_in.get("skill") or tool.get("skill") or "").strip()
            if slug not in allowed:
                return ToolOutput(
                    f"Tool {tool['name']} failed: unknown skill '{slug}'. "
                    f"Choose one of: {', '.join(allowed) or '(none)'}."
                )
            return ToolOutput(
                await run_script(
                    slug,
                    str(raw_in.get("script") or ""),
                    _runner_args(raw_in.get("args")),
                    timeout=tool.get("timeout"),
                    max_chars=int(tool.get("max_chars") or _SCRIPT_MAX_CHARS),
                )
            )
        a = _coerce(raw_in, tool["parameters"])
        a = {**(tool.get("defaults") or {}), **a}
        post = tool.get("postprocess") or ""
        res = await run_script(
            tool["skill"],
            tool["script"],
            script_argv(tool, a),
            timeout=tool.get("timeout"),
            # 有 postprocess 時原始輸出不會直接給模型，放寬上限讓 JSON 完整
            max_chars=400_000 if post else int(tool.get("max_chars") or _SCRIPT_MAX_CHARS),
            raw=bool(post),
        )
        events: list[dict[str, Any]] = []
        if post and isinstance(res, tuple):
            stdout, err, code = res
            if code == 0 and stdout.strip():
                text, events = await _postprocess(post, stdout)
                text = f"Result of {tool['name']}:\n" + _truncate(text, int(tool.get("max_chars") or _SCRIPT_MAX_CHARS))
            else:
                text = f"Tool {tool['name']} failed (exit code {code}):\n" + _truncate(err or stdout or "(no output)", _STDERR_MAX_CHARS)
        else:
            text = res if isinstance(res, str) else str(res)
        if tool.get("result_note"):
            text += f"\n\n{tool['result_note']}"
        return ToolOutput(text, events)

    # --- HTTP 工具 ---
    args = _coerce(raw_in, tool["parameters"])
    # defaults（如 wait/timeout）先鋪底，模型明確給的值優先
    args = {**(tool.get("defaults") or {}), **args}
    path = tool["path"]
    for m in re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", path):
        if m in args:
            path = path.replace("{" + m + "}", str(args.pop(m)))
    base = _resolve_base(tool["base_url"])
    url = base + ("" if path.startswith("/") else "/") + path
    method = tool["method"]
    timeout = min(float(tool.get("timeout") or _DEFAULT_TIMEOUT), HTTP_TIMEOUT)
    attach = tool.get("attach_image")
    if attach:
        if not image:
            return ToolOutput(
                f"Tool {tool['name']} needs an image, but the user has not attached one in this "
                "conversation. Ask the user to attach the image to edit, then call the tool again."
            )
        field = str(attach.get("field") or "image")
        args[field] = [_as_data_url(image)] if attach.get("as") == "list" else _as_data_url(image)
        # 沒指定尺寸時沿用附圖的長寬比（伺服器預設 512x512 會把圖壓成正方形）
        if attach.get("size_from_image") and not (args.get("width") and args.get("height")):
            size = _image_size(image, int(attach.get("max_pixels") or 1024 * 1024), int(attach.get("multiple") or 32))
            if size:
                args["width"], args["height"] = size

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method in ("GET", "DELETE"):
                query = {
                    k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
                    for k, v in args.items()
                    if v is not None
                }
                resp = await client.request(method, url, params=query)
            else:
                tool = {**tool, "_sent": args}
                qnames = tool.get("query_params") or []
                query = {k: args.pop(k) for k in list(args) if k in qnames and args[k] is not None}
                resp = await client.request(method, url, params=query or None, json=args)
    except httpx.HTTPError as e:
        msg = f"Tool {tool['name']} failed: could not reach {url} ({e.__class__.__name__}: {e})"
        log.warning(msg)
        return ToolOutput(msg, [{"type": "error", "message": msg}] if tool.get("postprocess") else [])

    body = resp.text or ""
    data: Any = None
    try:
        data = resp.json()
        body = json.dumps(data, ensure_ascii=False, indent=1)
    except ValueError:
        pass
    if "{a1111_url}" in tool["base_url"]:
        body = rewrite_a1111_thumbs(body)

    limit = int(tool.get("max_chars") or _DEFAULT_MAX_CHARS)
    if resp.status_code >= 400:
        msg = f"Tool {tool['name']} returned HTTP {resp.status_code}:\n{_truncate(body, limit)}"
        log.warning(msg[:500])
        return ToolOutput(msg, [{"type": "error", "message": msg[:300]}] if tool.get("postprocess") else [])
    events: list[dict[str, Any]] = []
    if tool.get("postprocess") and (isinstance(data, (dict, list)) or tool["postprocess"] == "a1111_memory_after"):
        body, events = await _postprocess_http(tool["postprocess"], tool, base, data)
    text = f"Result of {tool['name']}:\n{_truncate(body, limit)}"
    if tool.get("result_note"):
        text += f"\n\n{tool['result_note']}"
    return ToolOutput(text, events)
