"""技能（Agent Skills）外掛：掃描 SKILLS_DIR、解析 SKILL.md、組成注入給模型的提示詞。

相容 Anthropic / Codex 的 Agent Skill 格式：每個技能是一個子資料夾，內含
  SKILL.md          —— YAML frontmatter（name / description）＋ Markdown 指示本體
  references/*.md   —— 選用的補充說明（一起注入，受長度上限保護）
  scripts/ assets/  —— 選用（本系統為純網頁，不執行腳本；見「轉接層」）

技能與引擎無關：選定後，其指示會被注入到 Ollama / Claude / Codex 任一引擎的
system prompt，所以同一個技能在所有引擎都能用。出圖一律走系統既有的 A1111 工具。
"""
from __future__ import annotations

import re
import shutil
from typing import Any

import settings_store
from config import SKILL_MAX_CHARS

# 單一 SKILL.md 內容上限（防止超大檔塞爆）
_MAX_SKILL_BYTES = 200_000


def _base():
    """目前的技能目錄（UI 可在設定頁切換並持久化）。"""
    return settings_store.get_skills_dir()

# 「執行環境轉接層」：永遠接在技能指示後面（不會被長度上限截掉）。
# 把社群技能假設的 image_gen / shell / 檔案系統，對應到本系統真正的能力。
_ADAPTER_NOTE = (
    "\n\n# Runtime adapter (READ THIS — overrides the skill where they conflict)\n"
    "You are running inside a web chat app, NOT a shell. You have NO filesystem, NO "
    "terminal, and you CANNOT run scripts. If the active skill tells you to run a "
    "script, write/read files, or maintain a folder (e.g. an `img-memory` directory or "
    "a `manage_*.py` helper), treat those as OPTIONAL bookkeeping: you may briefly "
    "describe them, but do NOT claim you executed them.\n"
    "Your ONLY image generator is the app's LOCAL Stable Diffusion (A1111). Whenever the "
    "skill says to use 'image_gen', a built-in image tool, or to generate/show/render an "
    "image or reference sheet, use THIS image capability — it renders inline in the chat. "
    "Write Stable Diffusion prompts as comma-separated English danbooru-style tags (for "
    "consistent characters, reuse the same character tags / LoRA / seed). Images you "
    "generated earlier in this conversation count as the 'visible references'."
)


def _safe_slug(slug: str) -> str | None:
    """只允許單層、無路徑穿越的資料夾名。"""
    slug = (slug or "").strip()
    if not slug or "/" in slug or "\\" in slug or slug.startswith(".") or ".." in slug:
        return None
    return slug


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
    }


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


def build_auto_prompt(max_chars: int = SKILL_MAX_CHARS) -> str:
    """Auto 模式：把所有技能的目錄＋（受限的）指示注入，讓模型自行判斷該不該用、用哪個。"""
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
    return text + _ADAPTER_NOTE


def build_prompt(slug: str, max_chars: int = SKILL_MAX_CHARS) -> str:
    """把技能組成要注入 system 的字串：標題＋描述＋本體＋（受限的）references＋轉接層。

    references 依長度上限逐份加入；轉接層永遠接在最後（不被截斷）。找不到技能回空字串。
    """
    skill = get_skill(slug)
    if not skill:
        return ""

    head = f"# Active skill: {skill['name']}"
    if skill["description"]:
        head += f"\n{skill['description']}"
    text = f"{head}\n\n{skill['body']}".strip()

    for r in skill["references"]:
        addition = f"\n\n## Reference: {r['name']}\n{r['content'].strip()}"
        if len(text) + len(addition) > max_chars:
            break
        text += addition

    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n…(truncated)"

    return text + _ADAPTER_NOTE
