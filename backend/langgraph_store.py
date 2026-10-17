"""LangGraph 工作流專案：官方 langgraph.json + Python，放在工作流資料夾/<專案>/。

工作流資料夾預設 LANGGRAPH_DIR，可在工作流頁面換（settings_store.langgraph_dir）。

- langgraph.json 照官方格式：graphs（id → "./檔案.py:變數"）、dependencies（"."、"./子資料夾"、
  套件名）、env（.env 路徑或 {名稱: 值}）；其他欄位（python_version、dockerfile_lines…）不使用。
- 每個專案一個 venv（LANGGRAPH_ENV_DIR/<資料夾代號>/<專案>/）：一律裝 langgraph，再依 dependencies 安裝——
  本地資料夾有 pyproject.toml / setup.py 就 pip install -e，只有 requirements.txt 就 -r 並加進
  sys.path，其餘字串當套件名。依賴檔一改，狀態就變成「需要重新安裝」。
- .env（與 langgraph.json 指定的 env 檔）只能寫、不能讀回瀏覽器。
執行與檢視圖在 langgraph_exec.py，執行紀錄在 langgraph_history.py。
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import sys
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, AsyncIterator

import settings_store
from config import (
    LANGGRAPH_DIR,
    LANGGRAPH_ENV_DIR,
    LANGGRAPH_INSTALL_TIMEOUT,
    LANGGRAPH_WORK_DIR,
)

CONFIG_NAME = "langgraph.json"
EXAMPLES_DIR = Path(__file__).parent / "langgraph_examples"
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
# 不列出、不上傳的資料夾
SKIP_DIRS = {".venv", "venv", "env", "__pycache__", ".git", "node_modules", ".langgraph_api",
             ".mypy_cache", ".pytest_cache", ".ruff_cache", ".idea", ".vscode"}
MAX_EDIT_BYTES = 1_000_000  # 瀏覽器編輯器讀得到的檔案大小上限
MAX_UPLOAD_FILES = 2000
MAX_UPLOAD_BYTES = 50_000_000
_MARKER = "webui-installed.json"
_installing: set[str] = set()


def base() -> Path:
    d = settings_store.get_langgraph_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def folder_key() -> str:
    """目前工作流資料夾的代號：venv、工作目錄與執行紀錄依它分開，換資料夾不會混到同名專案。"""
    d = settings_store.get_langgraph_dir().resolve()
    if d == Path(LANGGRAPH_DIR).resolve():
        return "default"
    return hashlib.sha1(str(d).encode()).hexdigest()[:10]


def valid_slug(slug: str) -> bool:
    return bool(_SLUG_RE.match(slug or "")) and slug not in (".", "..")


def project_dir(slug: str) -> Path:
    if not valid_slug(slug):
        raise ValueError(f"專案名稱只能用英數字、. _ -：{slug!r}")
    d = base() / slug
    if not (d / CONFIG_NAME).is_file():
        raise FileNotFoundError(f"找不到專案「{slug}」（或沒有 {CONFIG_NAME}）")
    return d


def safe_rel(path: str) -> PurePosixPath:
    """專案內的相對路徑：不能是絕對路徑、不能有 ..、不能進 SKIP_DIRS。"""
    raw = (path or "").replace("\\", "/").strip()
    rel = PurePosixPath(raw)
    if not raw or rel.is_absolute() or re.match(r"^[A-Za-z]:", raw):
        raise ValueError(f"不合法的路徑：{path!r}")
    parts = [p for p in rel.parts if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts) or any(p in SKIP_DIRS for p in parts):
        raise ValueError(f"不合法的路徑：{path!r}")
    return PurePosixPath(*parts)


# ---------------- langgraph.json ----------------

def read_config(pdir: Path) -> dict[str, Any]:
    """解析並整理 langgraph.json；格式錯誤丟 ValueError（訊息給使用者看）。"""
    try:
        raw = json.loads((pdir / CONFIG_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"{CONFIG_NAME} 讀不了：{e}") from e
    if not isinstance(raw, dict):
        raise ValueError(f"{CONFIG_NAME} 要是 JSON 物件")
    graphs_raw = raw.get("graphs")
    if not isinstance(graphs_raw, dict) or not graphs_raw:
        raise ValueError(f"{CONFIG_NAME} 缺少 graphs（例如 {{\"agent\": \"./agent.py:graph\"}}）")
    graphs: dict[str, str] = {}
    unsupported: dict[str, str] = {}
    for gid, spec in graphs_raw.items():
        path = spec.get("path") if isinstance(spec, dict) else spec
        if not isinstance(path, str) or ":" not in path:
            raise ValueError(f"graph「{gid}」要寫成 './檔案.py:變數'")
        if path.split(":", 1)[0].endswith((".ts", ".mts", ".js", ".mjs")):
            unsupported[str(gid)] = "只支援 Python 的圖（JS/TS 不支援）"
        else:
            graphs[str(gid)] = path
    deps = raw.get("dependencies", ["."])
    if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
        raise ValueError("dependencies 要是字串陣列")
    env = raw.get("env")
    if env is not None and not isinstance(env, (str, dict)):
        raise ValueError("env 要是 .env 檔路徑或 {名稱: 值}")
    return {"graphs": graphs, "unsupported": unsupported, "dependencies": deps, "env": env,
            "python_version": raw.get("python_version")}


def _read_env_file(p: Path) -> dict[str, str]:
    import skill_tools

    return skill_tools._read_env_file(p)


def env_values(pdir: Path, cfg: dict[str, Any]) -> dict[str, str]:
    env = cfg.get("env")
    if isinstance(env, dict):
        return {str(k): str(v) for k, v in env.items()}
    if isinstance(env, str):
        with contextlib.suppress(ValueError):
            return _read_env_file(pdir / safe_rel(env))
    return {}


def _secret_paths(cfg: dict[str, Any] | None) -> set[str]:
    out = set()
    if cfg and isinstance(cfg.get("env"), str):
        with contextlib.suppress(ValueError):
            out.add(str(safe_rel(cfg["env"])))
    return out


def is_secret(rel: PurePosixPath, cfg: dict[str, Any] | None) -> bool:
    return rel.name == ".env" or rel.name.startswith(".env.") or str(rel) in _secret_paths(cfg)


# ---------------- 依賴 / venv ----------------

def env_dir(slug: str) -> Path:
    return LANGGRAPH_ENV_DIR / folder_key() / slug


def work_dir(slug: str) -> Path:
    return LANGGRAPH_WORK_DIR / folder_key() / slug


def venv_python(slug: str) -> Path:
    d = env_dir(slug)
    return d / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def install_plan(pdir: Path, cfg: dict[str, Any]) -> dict[str, list[str]]:
    """{"packages": [...], "requirements": [檔案], "editable": [資料夾], "paths": [加進 sys.path]}"""
    plan: dict[str, list[str]] = {"packages": ["langgraph"], "requirements": [], "editable": [], "paths": []}
    for dep in cfg["dependencies"]:
        dep = dep.strip()
        if not dep:
            continue
        if dep == "." or dep.startswith(("./", "../")) or dep.startswith("."):
            d = (pdir / dep).resolve()
            if pdir.resolve() not in (d, *d.parents):
                raise ValueError(f"dependencies 的本地資料夾要在專案裡：{dep}")
            if not d.is_dir():
                raise ValueError(f"dependencies 的資料夾不存在：{dep}")
            if (d / "pyproject.toml").is_file() or (d / "setup.py").is_file():
                plan["editable"].append(str(d))
            else:
                if (d / "requirements.txt").is_file():
                    plan["requirements"].append(str(d / "requirements.txt"))
                plan["paths"].append(str(d))
        elif dep.startswith("-"):
            raise ValueError(f"dependencies 不能放 pip 選項：{dep}")
        elif dep.lower() != "langgraph":
            plan["packages"].append(dep)
    return plan


def deps_hash(pdir: Path, cfg: dict[str, Any]) -> str:
    h = hashlib.sha256(json.dumps(cfg["dependencies"]).encode())
    with contextlib.suppress(ValueError):
        plan = install_plan(pdir, cfg)
        for d in plan["editable"] + plan["paths"]:
            for name in ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt"):
                f = Path(d) / name
                if f.is_file():
                    h.update(name.encode() + f.read_bytes())
    return h.hexdigest()[:16]


def venv_status(slug: str, pdir: Path | None = None, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    if str(env_dir(slug)) in _installing:
        return {"state": "installing"}
    marker = env_dir(slug) / _MARKER
    if not venv_python(slug).exists() or not marker.is_file():
        return {"state": "missing"}
    try:
        info = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": "missing"}
    state = "ready"
    if pdir is not None and cfg is not None and info.get("hash") != deps_hash(pdir, cfg):
        state = "outdated"
    return {"state": state, "installed_at": info.get("at"), "langgraph": info.get("langgraph")}


def _proc_env(slug: str) -> dict[str, str]:
    work = work_dir(slug)
    work.mkdir(parents=True, exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH") or "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(work),  # 不給真正的家目錄（容器內掛著 ~/.claude、~/.codex）
        "LANG": os.environ.get("LANG") or "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INPUT": "1",
        "PIP_CACHE_DIR": str(LANGGRAPH_ENV_DIR / ".pip-cache"),
    }
    for k in ("http_proxy", "https_proxy", "no_proxy", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
              "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "PIP_INDEX_URL",
              "PIP_EXTRA_INDEX_URL", "TZ"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


async def _stream_cmd(cmd: list[str], cwd: Path, env: dict[str, str], deadline: float) -> AsyncIterator[str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=str(cwd), env=env, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        assert proc.stdout is not None
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError(f"安裝超過 {LANGGRAPH_INSTALL_TIMEOUT:.0f} 秒，已停止")
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=left)
            except asyncio.TimeoutError:
                continue
            if not line:
                break
            yield line.decode("utf-8", "replace").rstrip()
        code = await proc.wait()
        if code != 0:
            raise RuntimeError(f"指令失敗（exit {code}）：{shlex.join(cmd[2:] if cmd[1:2] == ['-m'] else cmd)}")
    finally:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, 9)
            with contextlib.suppress(Exception):
                await proc.wait()


async def install(slug: str) -> AsyncIterator[str]:
    """建立 / 更新專案的 venv，逐行回傳安裝紀錄；失敗丟例外。"""
    pdir = project_dir(slug)
    cfg = read_config(pdir)
    plan = install_plan(pdir, cfg)
    key = str(env_dir(slug))
    if key in _installing:
        raise ValueError("這個專案正在安裝依賴")
    _installing.add(key)
    try:
        env = _proc_env(slug)
        deadline = time.monotonic() + LANGGRAPH_INSTALL_TIMEOUT
        edir = env_dir(slug)
        py = venv_python(slug)
        if not py.exists():
            edir.parent.mkdir(parents=True, exist_ok=True)
            yield f"$ python -m venv {edir.name}"
            async for line in _stream_cmd([sys.executable, "-m", "venv", str(edir)], pdir, env, deadline):
                yield line
        pip = [str(py), "-m", "pip", "install"]
        steps = [pip + plan["packages"]]
        steps += [pip + ["-r", r] for r in plan["requirements"]]
        steps += [pip + ["-e", d] for d in plan["editable"]]
        for cmd in steps:
            yield "$ pip install " + shlex.join(
                os.path.relpath(a, pdir) if a.startswith(str(pdir)) else a for a in cmd[4:]
            )
            async for line in _stream_cmd(cmd, pdir, env, deadline):
                yield line
        version = ""
        async for line in _stream_cmd(
            [str(py), "-c", "from importlib.metadata import version; print(version('langgraph'))"],
            pdir, env, deadline,
        ):
            version = line.strip() or version
        (edir / _MARKER).write_text(
            json.dumps({"hash": deps_hash(pdir, cfg), "at": time.time(), "langgraph": version,
                        "paths": plan["paths"]}),
            encoding="utf-8",
        )
        yield f"完成：langgraph {version}"
    finally:
        _installing.discard(key)


def extra_paths(slug: str) -> list[str]:
    """安裝時記下的「只有 requirements.txt 的本地資料夾」，執行時加進 sys.path。"""
    try:
        return list(json.loads((env_dir(slug) / _MARKER).read_text(encoding="utf-8")).get("paths") or [])
    except (OSError, ValueError):
        return []


# ---------------- 專案與檔案 ----------------

def _iter_files(pdir: Path) -> list[Path]:
    out = []
    for root, dirs, files in os.walk(pdir):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.endswith(".egg-info"))
        for f in sorted(files):
            p = Path(root) / f
            if not p.is_symlink() and not f.endswith((".pyc", ".pyo")):
                out.append(p)
    return out


def describe(pdir: Path) -> str:
    """專案的一行說明：README.md 第一個標題或第一段文字。"""
    readme = next((pdir / n for n in ("README.md", "readme.md", "README.txt") if (pdir / n).is_file()), None)
    if not readme:
        return ""
    with contextlib.suppress(OSError, UnicodeDecodeError):
        for line in readme.read_text(encoding="utf-8").splitlines():
            text = line.strip().lstrip("#").strip()
            if text:
                return text[:200]
    return ""


def _updated_at(pdir: Path) -> float:
    with contextlib.suppress(OSError):
        return max((p.stat().st_mtime for p in _iter_files(pdir)), default=pdir.stat().st_mtime)
    return 0.0


def list_projects() -> list[dict[str, Any]]:
    import langgraph_history

    out = []
    for d in sorted(base().iterdir(), key=lambda e: e.name.lower()):
        if not d.is_dir() or not (d / CONFIG_NAME).is_file() or not valid_slug(d.name):
            continue
        item: dict[str, Any] = {"slug": d.name, "description": describe(d), "updated_at": _updated_at(d)}
        try:
            cfg = read_config(d)
            item["graphs"] = list(cfg["graphs"])
            item["venv"] = venv_status(d.name, d, cfg)
        except ValueError as e:
            item["graphs"], item["error"] = [], str(e)
            item["venv"] = venv_status(d.name)
        item["last_run"] = langgraph_history.last_run(d.name)
        out.append(item)
    return out


def get_project(slug: str) -> dict[str, Any]:
    pdir = project_dir(slug)
    out: dict[str, Any] = {"slug": slug, "path": str(pdir), "description": describe(pdir)}
    cfg = None
    try:
        cfg = read_config(pdir)
        out["config"] = {k: cfg[k] for k in ("graphs", "unsupported", "dependencies", "python_version")}
        out["config"]["env"] = (cfg["env"] if isinstance(cfg["env"], str)
                                else sorted(cfg["env"]) if isinstance(cfg["env"], dict) else None)
        out["venv"] = venv_status(slug, pdir, cfg)
    except ValueError as e:
        out["error"] = str(e)
        out["venv"] = venv_status(slug)
    files = []
    for p in _iter_files(pdir):
        rel = PurePosixPath(p.relative_to(pdir).as_posix())
        files.append({"path": str(rel), "size": p.stat().st_size, "secret": is_secret(rel, cfg)})
    out["files"] = files
    return out


def _cfg_or_none(pdir: Path) -> dict[str, Any] | None:
    try:
        return read_config(pdir)
    except ValueError:
        return None


def read_file(slug: str, path: str) -> str:
    pdir = project_dir(slug)
    rel = safe_rel(path)
    if is_secret(rel, _cfg_or_none(pdir)):
        raise PermissionError("環境變數檔只能覆寫，不能讀取內容")
    f = pdir / rel
    if not f.is_file() or f.is_symlink():
        raise FileNotFoundError(f"找不到 {rel}")
    if f.stat().st_size > MAX_EDIT_BYTES:
        raise ValueError(f"{rel} 太大，無法在瀏覽器編輯")
    try:
        return f.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ValueError(f"{rel} 不是文字檔") from None


def write_file(slug: str, path: str, content: str) -> dict[str, Any]:
    pdir = project_dir(slug)
    rel = safe_rel(path)
    if len(content.encode("utf-8")) > MAX_EDIT_BYTES:
        raise ValueError("檔案太大")
    if str(rel) == CONFIG_NAME:  # 先確認還是合法的 langgraph.json，免得把專案弄壞
        try:
            json.loads(content)
        except ValueError as e:
            raise ValueError(f"{CONFIG_NAME} 不是合法的 JSON：{e}") from e
    f = pdir / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    return get_project(slug)


def delete_file(slug: str, path: str) -> dict[str, Any]:
    pdir = project_dir(slug)
    rel = safe_rel(path)
    if str(rel) == CONFIG_NAME:
        raise ValueError(f"不能刪除 {CONFIG_NAME}（要刪整個專案請用刪除專案）")
    f = pdir / rel
    if f.is_file():
        f.unlink()
    return get_project(slug)


def list_templates() -> list[dict[str, str]]:
    """新增專案可選的範本（langgraph_examples/ 底下的資料夾）：[{"id", "description"}]。"""
    return [{"id": d.name, "description": describe(d)} for d in sorted(EXAMPLES_DIR.iterdir())
            if d.is_dir() and (d / CONFIG_NAME).is_file() and valid_slug(d.name)]


def create_project(slug: str, template: str = "example") -> dict[str, Any]:
    if not valid_slug(slug):
        raise ValueError("專案名稱只能用英數字、. _ -（開頭要是英數字）")
    d = base() / slug
    if d.exists():
        raise FileExistsError(f"已有專案「{slug}」")
    src = EXAMPLES_DIR / template
    if template and valid_slug(template) and src.is_dir():  # 範本只能是 langgraph_examples/ 底下的資料夾
        shutil.copytree(src, d, ignore=shutil.ignore_patterns(*SKIP_DIRS, "*.pyc"))
    else:
        d.mkdir(parents=True)
        (d / CONFIG_NAME).write_text(
            json.dumps({"dependencies": ["."], "graphs": {"agent": "./agent.py:graph"}, "env": ".env"},
                       indent=2) + "\n", encoding="utf-8")
        (d / "agent.py").write_text(_EMPTY_AGENT, encoding="utf-8")
    return get_project(slug)


def delete_project(slug: str) -> None:
    import langgraph_history

    if not valid_slug(slug):
        raise ValueError("不合法的專案名稱")
    if str(env_dir(slug)) in _installing:
        raise ValueError("這個專案正在安裝依賴，請稍後再刪")
    for d in (base() / slug, env_dir(slug), work_dir(slug), langgraph_history.runs_dir(slug)):
        if d.exists():
            shutil.rmtree(d)


def _new_slug(new_slug: str) -> Path:
    new_slug = (new_slug or "").strip()
    if not valid_slug(new_slug):
        raise ValueError("專案名稱只能用英數字、. _ -（開頭要是英數字）")
    dest = base() / new_slug
    if dest.exists():
        raise FileExistsError(f"已有專案「{new_slug}」")
    return dest


def rename_project(slug: str, new_slug: str) -> dict[str, Any]:
    """改名：專案資料夾、執行紀錄跟著搬；venv 刪掉（editable 安裝記著舊路徑），要重新安裝。"""
    import langgraph_history

    src = project_dir(slug)
    dest = _new_slug(new_slug)
    if str(env_dir(slug)) in _installing:
        raise ValueError("這個專案正在安裝依賴，請稍後再改名")
    src.rename(dest)
    runs_old, runs_new = langgraph_history.runs_dir(slug), langgraph_history.runs_dir(dest.name)
    if runs_old.exists():
        runs_new.parent.mkdir(parents=True, exist_ok=True)
        runs_old.rename(runs_new)
    for d in (env_dir(slug), work_dir(slug)):
        if d.exists():
            shutil.rmtree(d)
    return get_project(dest.name)


def duplicate_project(slug: str, new_slug: str) -> dict[str, Any]:
    """複製一份專案檔案（含 .env；不含 venv 與執行紀錄）。"""
    src = project_dir(slug)
    dest = _new_slug(new_slug)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(*SKIP_DIRS, "*.pyc", "*.egg-info"))
    return get_project(dest.name)


def export_zip(slug: str) -> bytes:
    """專案打包成 zip（不含 .env 等環境變數檔、venv、快取）：裡面的祕密不會被下載到瀏覽器。"""
    pdir = project_dir(slug)
    cfg = _cfg_or_none(pdir)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in _iter_files(pdir):
            rel = PurePosixPath(f.relative_to(pdir).as_posix())
            if not is_secret(rel, cfg):
                zf.write(f, f"{slug}/{rel}")
    return buf.getvalue()


def _strip_top(paths: list[str]) -> str:
    """上傳的檔案都在同一個上層資料夾、且 langgraph.json 在裡面 → 回那個資料夾名（要去掉）。"""
    if CONFIG_NAME in paths:
        return ""
    tops = {p.split("/", 1)[0] for p in paths}
    if len(tops) == 1 and f"{next(iter(tops))}/{CONFIG_NAME}" in paths:
        return next(iter(tops)) + "/"
    return ""


def import_files(slug: str, files: list[tuple[str, bytes]], *, replace: bool = False) -> dict[str, Any]:
    """上傳整個專案（資料夾或 zip 解出的檔案）。replace＝先清掉原本的檔案（venv 保留）。"""
    if not valid_slug(slug):
        raise ValueError("專案名稱只能用英數字、. _ -（開頭要是英數字）")
    if len(files) > MAX_UPLOAD_FILES:
        raise ValueError(f"檔案太多（上限 {MAX_UPLOAD_FILES}）")
    if sum(len(b) for _, b in files) > MAX_UPLOAD_BYTES:
        raise ValueError(f"檔案太大（上限 {MAX_UPLOAD_BYTES // 1_000_000} MB）")
    cleaned: list[tuple[str, bytes]] = []
    for path, data in files:
        norm = (path or "").replace("\\", "/").lstrip("/")
        with contextlib.suppress(ValueError):  # SKIP_DIRS 等直接略過
            cleaned.append((str(safe_rel(norm)), data))
    top = _strip_top([p for p, _ in cleaned])
    cleaned = [(p[len(top):], b) for p, b in cleaned if p.startswith(top) and p[len(top):]]
    if not any(p == CONFIG_NAME for p, _ in cleaned):
        raise ValueError(f"上傳的檔案裡沒有 {CONFIG_NAME}（要在最上層，或唯一的資料夾裡）")
    d = base() / slug
    if d.exists() and replace:
        shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
    for rel, data in cleaned:
        f = d / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
    return get_project(slug)


def import_zip(slug: str, data: bytes, *, replace: bool = False) -> dict[str, Any]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ValueError("不是合法的 zip 檔") from e
    files = []
    total = 0
    for info in zf.infolist():
        if info.is_dir():
            continue
        if (info.external_attr >> 16) & 0o170000 == 0o120000:  # symlink
            continue
        total += info.file_size
        if total > MAX_UPLOAD_BYTES:
            raise ValueError(f"解壓後太大（上限 {MAX_UPLOAD_BYTES // 1_000_000} MB）")
        files.append((info.filename, zf.read(info)))
    return import_files(slug, files, replace=replace)


_EMPTY_AGENT = '''"""最小的 LangGraph 圖：把輸入交給 app 目前選的 LLM。"""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

import webui_app


class State(TypedDict, total=False):
    question: str
    answer: str


def answer(state: State) -> State:
    return {"answer": webui_app.chat(state["question"])}


builder = StateGraph(State)
builder.add_node("answer", answer)
builder.add_edge(START, "answer")
builder.add_edge("answer", END)
graph = builder.compile()
'''
