"""一句想法 → 英文場景 → danbooru 標籤 → A1111 生圖 → LLM 看圖檢查 → 不符合就改標籤重畫。

示範：webui_app.chat / generate_image、讓模型看 A1111 生成的圖（images=[...]）、
條件分支與迴圈。輸入：{"idea": "..."}（在聊天裡也可以直接打 /workflow example:illustrate 一段文字）。
"""
import json
import re
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

import webui_app

MAX_DRAWS = 2


class Input(TypedDict):
    idea: str


class Output(TypedDict, total=False):
    scene: str
    prompt: str
    image: str
    review: str
    draws: int


class State(Input, Output, total=False):
    fix: str


def write_scene(state: State) -> dict:
    scene = webui_app.chat(
        "Turn this idea into a vivid picture description: 2-3 English sentences about the "
        "subject, what they do, the place, the time of day and the light. Only the "
        f"description, no title.\n\nIdea: {state['idea']}"
    )
    return {"scene": scene.strip(), "draws": 0}


def make_prompt(state: State) -> dict:
    fix = f"\nThe previous picture had this problem, fix it: {state['fix']}" if state.get("fix") else ""
    raw = webui_app.chat(
        "Write a Stable Diffusion prompt for this scene as 15-30 comma-separated English "
        "danbooru tags (count tag first, e.g. 1girl, solo). Only the tags, one line, no "
        f"quality words.{fix}\n\nScene: {state['scene']}"
    )
    tags = re.sub(r"\s+", " ", raw.replace("\n", ", ")).strip().strip(",")
    return {"prompt": tags}


def draw(state: State) -> dict:
    webui_app.emit(f"drawing #{state.get('draws', 0) + 1}")
    img = webui_app.generate_image(state["prompt"])
    return {"image": img["url"], "draws": state.get("draws", 0) + 1}


def review(state: State) -> dict:
    """讓 LLM 真的看 A1111 生成的圖，判斷有沒有畫對。"""
    try:
        answer = webui_app.chat(
            "Look at the attached image. Does it match this scene? Reply with JSON only: "
            '{"ok": true or false, "seen": "one sentence about what the image shows", '
            '"fix": "what to change, empty if ok"}\n\nScene: ' + state["scene"],
            images=[state["image"]],
        )
    except RuntimeError as e:  # 模型看不到圖（不是視覺模型）時就不檢查
        return {"review": f"skipped: {e}", "fix": ""}
    match = re.search(r"\{.*\}", answer, re.S)
    try:
        verdict = json.loads(match.group(0)) if match else {}
    except ValueError:
        verdict = {}
    ok = bool(verdict.get("ok", True))
    seen = verdict.get("seen") or answer.strip()[:300]
    return {"review": ("ok: " if ok else "redo: ") + seen, "fix": "" if ok else verdict.get("fix", "")}


def again(state: State) -> str:
    return "make_prompt" if state.get("fix") and state.get("draws", 0) < MAX_DRAWS else END


builder = StateGraph(State, input_schema=Input, output_schema=Output)
builder.add_node("write_scene", write_scene)
builder.add_node("make_prompt", make_prompt)
builder.add_node("draw", draw)
builder.add_node("review", review)
builder.add_edge(START, "write_scene")
builder.add_edge("write_scene", "make_prompt")
builder.add_edge("make_prompt", "draw")
builder.add_edge("draw", "review")
builder.add_conditional_edges("review", again, ["make_prompt", END])
graph = builder.compile()
