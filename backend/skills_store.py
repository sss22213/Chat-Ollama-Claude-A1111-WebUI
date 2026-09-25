"""技能（Agent Skills）外掛：掃描 SKILLS_DIR、解析 SKILL.md、組成注入給模型的提示詞。

相容 Anthropic / Codex 的 Agent Skill 格式：每個技能是一個子資料夾，內含
  SKILL.md          —— YAML frontmatter（name / description）＋ Markdown 指示本體
  references/*.md   —— 選用的補充說明（一起注入，受長度上限保護）
  scripts/ assets/  —— 選用；設定頁開啟「允許技能執行腳本」後，*.py 可由模型透過
                       run_skill_script 工具在伺服器執行（見 skill_tools）

技能與引擎無關：選定後，其指示會被注入到 Ollama / Claude / Codex 任一引擎的
system prompt，所以同一個技能在所有引擎都能用。出圖一律走系統既有的 A1111 工具。
"""
from __future__ import annotations

import json
import re
import shutil
from typing import Any

import settings_store
import skill_tools

# 單一 SKILL.md 內容上限（防止超大檔塞爆）
_MAX_SKILL_BYTES = 200_000


def _base():
    """目前的技能目錄（UI 可在設定頁切換並持久化）。"""
    return settings_store.get_skills_dir()

# 「執行環境轉接層」：永遠接在技能指示後面（不會被長度上限截掉）。
# 把社群技能假設的 image_gen / shell / 檔案系統，對應到本系統真正的能力。
_ADAPTER_HEAD = "\n\n# Runtime adapter (READ THIS — overrides the skill where they conflict)\n"
_NO_SCRIPTS_NOTE = (
    "You are running inside a web chat app, NOT a shell. You have NO filesystem, NO "
    "terminal, and you CANNOT run scripts. If the active skill tells you to run a "
    "script, write/read files, or maintain a folder (e.g. an `img-memory` directory or "
    "a `manage_*.py` helper), treat those as OPTIONAL bookkeeping: you may briefly "
    "describe them, but do NOT claim you executed them.\n"
)
_SCRIPTS_NOTE = (
    "You are running inside a web chat app, NOT an interactive shell, but you CAN run the "
    "skill's bundled Python scripts on the app server through the `run_skill_script` tool "
    "(listed with the other tools). Whenever the skill's instructions say to run a script — "
    "e.g. `python ./scripts/foo.py models --query \"x\"` (the path may be written for "
    "Windows or another folder layout) — call run_skill_script with script='foo.py' and "
    "args=['models','--query','x'] instead of printing the command, wait for the result, "
    "and then continue with the skill's workflow. Scripts run in a persistent per-skill work "
    "folder on the server, so files they write are still there in later turns. You cannot "
    "run arbitrary shell commands or install packages. Never claim you ran a script unless "
    "you actually called the tool and got its output.\n"
)
_IMAGE_NOTE = (
    "Your ONLY image generator is the app's LOCAL Stable Diffusion (A1111). Whenever the "
    "skill says to use 'image_gen', a built-in image tool, or to generate/show/render an "
    "image or reference sheet, use THIS image capability — it renders inline in the chat. "
    "Write Stable Diffusion prompts as comma-separated English danbooru-style tags (for "
    "consistent characters, reuse the same character tags / LoRA / seed). Images you "
    "generated earlier in this conversation count as the 'visible references'."
)
# 舊名稱保留給既有呼叫端／測試
_ADAPTER_NOTE = _ADAPTER_HEAD + _NO_SCRIPTS_NOTE + _IMAGE_NOTE


def _adapter_note(tools: list[dict[str, Any]]) -> str:
    """有腳本工具（run_skill_script 或 tools.json 的 kind=script）時改用「可以跑腳本」版本。"""
    can_run = any(skill_tools.is_script_tool(t) for t in tools)
    return _ADAPTER_HEAD + (_SCRIPTS_NOTE if can_run else _NO_SCRIPTS_NOTE) + _IMAGE_NOTE


def _safe_slug(slug: str) -> str | None:
    """只允許單層、無路徑穿越的資料夾名。"""
    slug = (slug or "").strip()
    if not slug or "/" in slug or "\\" in slug or slug.startswith(".") or ".." in slug:
        return None
    return slug


AUTO = "__auto__"


def parse_selection(value: str | list[str] | None) -> list[str]:
    """把前端送來的技能選擇整理成 slug 清單。

    接受 ""（不啟用）、"__auto__"（模型自選）、"a,b,c" 或陣列；非法 slug 略過、去重、保序。
    含 __auto__ 時只回 [__auto__]（自動模式已涵蓋所有技能）。"""
    if not value:
        return []
    parts = value if isinstance(value, list) else str(value).split(",")
    out: list[str] = []
    for raw in parts:
        item = str(raw or "").strip()
        if item == AUTO:
            return [AUTO]
        safe = _safe_slug(item)
        if safe and safe not in out:
            out.append(safe)
    return out


def _parse_frontmatter(text: str) -> tuple[str, str, str]:
    """解析 `---\\n...\\n---\\n` frontmatter，回 (name, description, body)。

    只取 name / description（單行、可被引號包住）；其餘忽略。沒有 frontmatter
    時 body＝全文。"""
    name = desc = ""
    body = text
    m = re.match(r"^﻿?---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if m:
        fm, body = m.group(1), m.group(2)
        for line in fm.splitlines():
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key = key.strip().lower()
            val = val.strip().strip('"').strip("'").strip()
            if key == "name" and not name:
                name = val
            elif key == "description" and not desc:
                desc = val
    return name, desc, body.strip()


def list_skills() -> list[dict[str, Any]]:
    """列出可用技能（給前端選單）。掃不到目錄就回空清單。"""
    out: list[dict[str, Any]] = []
    base = _base()
    try:
        if not base.is_dir():
            return out
        for d in sorted(base.iterdir(), key=lambda e: e.name.lower()):
            if not d.is_dir():
                continue
            f = d / "SKILL.md"
            if not f.is_file():
                continue
            try:
                name, desc, _ = _parse_frontmatter(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            out.append(
                {
                    "slug": d.name,
                    "name": name or d.name,
                    "description": desc,
                    "has_references": (d / "references").is_dir(),
                    "has_scripts": (d / "scripts").is_dir(),
                    "has_tools": (d / "tools.json").is_file(),
                }
            )
    except Exception:
        return out
    return out


def get_skill(slug: str) -> dict[str, Any] | None:
    """讀單一技能的完整內容（含 references）。slug 非法或找不到回 None。"""
    safe = _safe_slug(slug)
    if not safe:
        return None
    d = _base() / safe
    f = d / "SKILL.md"
    try:
        if not (d.is_dir() and f.is_file()):
            return None
        raw = f.read_text(encoding="utf-8")
        name, desc, body = _parse_frontmatter(raw)
    except Exception:
        return None

    refs: list[dict[str, str]] = []
    rdir = d / "references"
    if rdir.is_dir():
        for rf in sorted(rdir.glob("*.md")):
            try:
                refs.append({"name": rf.name, "content": rf.read_text(encoding="utf-8")})
            except Exception:
                continue

    return {
        "slug": safe,
        "name": name or safe,
        "description": desc,
        "body": body,
        "raw": raw,  # 完整 SKILL.md 原文（給管理 UI 編輯用）
        "references": refs,
        "tools": get_skill_tools(safe),
        "scripts": skill_tools.list_scripts(d),
    }


def get_skill_tools(slug: str) -> list[dict[str, Any]]:
    """讀技能資料夾內的 tools.json（API 工具宣告）；沒有或壞掉就回空清單。

    tools.json 只能由檔案系統放入（網頁編輯器只寫 SKILL.md），視為可信設定。
    格式見 skill_tools 模組說明。"""
    safe = _safe_slug(slug)
    if not safe:
        return []
    f = _base() / safe / "tools.json"
    try:
        if not f.is_file():
            return []
        raw = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return []
    return skill_tools.normalize(raw, safe)


def tools_for(skill: str | list[str] | None) -> list[dict[str, Any]]:
    """本回合可用的技能工具：指定技能（可多個，逗號分隔）＝它們的工具；__auto__＝所有技能的工具（同名取先）。

    設定頁「允許技能執行腳本」開啟時，凡是有 *.py 的技能會再多一個通用的
    run_skill_script 工具（多技能共用一個、以 skill 參數區分）。"""
    selected = parse_selection(skill)
    if not selected:
        return []
    slugs = [it["slug"] for it in list_skills()] if selected == [AUTO] else selected
    scripts_on = settings_store.get_skill_scripts()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for slug in slugs:
        for t in get_skill_tools(slug):
            # 腳本關閉時，tools.json 宣告的固定腳本工具也不給模型看
            if t["name"] in seen or (skill_tools.is_script_tool(t) and not scripts_on):
                continue
            seen.add(t["name"])
            out.append(t)
    if scripts_on:
        with_scripts = []
        for slug in slugs:
            d = skill_tools.skill_dir(slug)
            scripts = skill_tools.list_scripts(d) if d else []
            if scripts:
                with_scripts.append({"slug": slug, "scripts": scripts})
        runner = skill_tools.runner_tool(with_scripts)
        if runner and runner["name"] not in seen:
            out.append(runner)
    return out


def _tools_note(tools: list[dict[str, Any]]) -> str:
    """注入 system 的一行工具提示；完整說明由引擎自己帶（ollama function schema / Claude [[CALL]] 指示）。"""
    if not tools:
        return ""
    names = ", ".join(t["name"] for t in tools)
    return (
        "\n\nSkill tools available in this chat (real tools the app executes for you; "
        f"call them instead of guessing): {names}"
    )


def _resolve_in_base(safe: str):
    """確認 slug 解析後仍在技能目錄內（縱深防護）。回 Path 或 None。"""
    try:
        base = _base().resolve()
        d = (_base() / safe).resolve()
    except Exception:
        return None
    if d == base or base not in d.parents:
        return None
    return d


def save_skill(slug: str, content: str) -> dict[str, Any]:
    """新增或覆寫一個技能的 SKILL.md（管理 UI 用）。回 get_skill。"""
    safe = _safe_slug(slug)
    if not safe:
        raise ValueError("技能名稱（資料夾）非法")
    if not content or not content.strip():
        raise ValueError("SKILL.md 內容不可為空")
    if len(content.encode("utf-8")) > _MAX_SKILL_BYTES:
        raise ValueError("SKILL.md 內容過大")
    d = _resolve_in_base(safe)
    if d is None:
        raise ValueError("技能路徑非法")
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(content, encoding="utf-8")
    return get_skill(safe)


def delete_skill(slug: str) -> bool:
    """刪除一個技能資料夾（僅限本身含 SKILL.md 的合法技能）。"""
    safe = _safe_slug(slug)
    if not safe:
        raise ValueError("技能名稱非法")
    d = _resolve_in_base(safe)
    if d is None or not (d.is_dir() and (d / "SKILL.md").is_file()):
        return False
    shutil.rmtree(d)
    return True


def build_auto_prompt(max_chars: int | None = None) -> str:
    """Auto 模式：把所有技能的目錄＋（受限的）指示注入，讓模型自行判斷該不該用、用哪個。
    max_chars 省略＝用設定頁的上限（0＝無上限）。"""
    max_chars = _limit(max_chars)
    skills = [s for s in (get_skill(it["slug"]) for it in list_skills()) if s]
    if not skills:
        return ""
    head = (
        "# Available skills (you decide whether to use one)\n"
        "The user has NOT pinned a specific skill. The skills below are available. If the "
        "user's request clearly matches one, FOLLOW that skill's workflow for your reply. "
        "If none apply, just answer normally and do not mention skills."
    )
    catalog = "\n".join(f"- {s['name']}: {s['description']}" for s in skills)
    text = f"{head}\n\n## Skill catalog\n{catalog}"
    omitted = False
    for s in skills:
        block = f"\n\n## Skill: {s['name']}\n{s['body'].strip()}"
        if len(text) + len(block) > max_chars:
            omitted = True
            continue
        text += block
    if omitted:
        text += (
            "\n\n(Full instructions for some skills were omitted to save space — the "
            "catalog above still lists them by name.)"
        )
    # 工具提示永遠附上（不受長度上限影響）
    all_tools = tools_for("__auto__")
    return text + _tools_note(all_tools) + _adapter_note(all_tools)


def _limit(max_chars: int | None) -> int:
    """實際長度上限：沒指定就讀設定頁的值；0 或負數＝無上限（回傳一個極大值）。"""
    v = settings_store.get_skill_max_chars() if max_chars is None else int(max_chars)
    return v if v > 0 else 10**9


def _skill_text(skill: dict[str, Any], head: str, budget: int) -> str:
    """一個技能的注入文字：標題＋本體＋（預算內的）references；超過預算截斷。"""
    text = f"{head}\n\n{skill['body']}".strip()
    for r in skill["references"]:
        addition = f"\n\n## Reference: {r['name']}\n{r['content'].strip()}"
        if len(text) + len(addition) > budget:
            break
        text += addition
    if len(text) > budget:
        text = text[:budget].rstrip() + "\n…(truncated)"
    return text


def build_prompt(slug: str | list[str], max_chars: int | None = None) -> str:
    """把技能組成要注入 system 的字串：標題＋描述＋本體＋（受限的）references＋轉接層。

    max_chars 省略＝用設定頁的上限（0＝無上限，每個技能完整注入）。有上限且同時啟用多個技能時，
    每個技能各分得 max_chars/n（至少 3000）的預算；references 依長度預算逐份加入；
    工具目錄與轉接層永遠接在最後（不被截斷）。找不到任何技能回空字串。
    """
    max_chars = _limit(max_chars)
    slugs = parse_selection(slug)
    if slugs == [AUTO]:
        return build_auto_prompt(max_chars)
    found = [sk for sk in (get_skill(x) for x in slugs) if sk]
    if not found:
        return ""

    if len(found) == 1:
        skill = found[0]
        head = f"# Active skill: {skill['name']}"
        if skill["description"]:
            head += f"\n{skill['description']}"
        text = _skill_text(skill, head, max_chars)
    else:
        budget = max(max_chars // len(found), 3000)
        catalog = "\n".join(f"- {sk['name']}: {sk['description']}" for sk in found)
        text = (
            f"# Active skills ({len(found)})\n"
            "The user enabled these skills together. Follow each skill's instructions "
            "whenever the request falls under it; when several apply at once, combine "
            "them and prefer the more specific instruction on conflicts.\n\n"
            f"{catalog}"
        )
        for sk in found:
            head = f"## Skill: {sk['name']}"
            if sk["description"]:
                head += f"\n{sk['description']}"
            text += "\n\n" + _skill_text(sk, head, budget).replace(
                "\n## Reference: ", "\n### Reference: "
            )

    # 工具目錄永遠附上（不受長度上限截斷），模型才知道有哪些 API／腳本可用
    tools = tools_for([sk["slug"] for sk in found])
    return text + _tools_note(tools) + _adapter_note(tools)
