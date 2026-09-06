"""表情 / 臉部狀態類 danbooru tag（單一來源）。

用途：
- comic.py：分鏡 LLM 只能從這份清單挑每格表情；誤放在場景 prompt 裡的表情 tag
  會被搬到 expression、品質詞會被丟掉。
- loras.py：LoRA 觸發詞建 prompt 時略過表情類標籤。角色 LoRA 的高頻訓練標籤
  常含 blush / smile / open mouth，固定帶入每格會蓋掉該格的表情。

前端 comic/expressionTags.js 有同一份清單（組合提示詞時過濾角色卡），修改時請同步。
"""
from __future__ import annotations

import re

# 給分鏡 LLM 挑選的表情 tag（依類別排列）。全部用 danbooru 慣例：小寫、底線換空白。
EXPRESSION_TAGS: list[str] = [
    # 情緒
    "smile", "light smile", "grin", "smirk", "seductive smile", "sad smile", "laughing",
    "happy", "excited", "embarrassed", "shy", "nervous", "flustered", "worried", "sad",
    "crying", "tears", "sobbing", "scared", "terrified", "horrified", "surprised",
    "shocked", "confused", "thinking", "bored", "sleepy", "tired", "dazed", "pain",
    "angry", "furious", "annoyed", "frown", "pout", "scowl", "glaring", "serious",
    "determined", "smug", "disgust", "jealous", "expressionless",
    # 眼睛
    "closed eyes", "one eye closed", "wink", "half-closed eyes", "wide-eyed",
    "narrowed eyes", "squinting", "rolling eyes", "empty eyes", "@_@",
    "heart-shaped pupils", "sparkling eyes", "glowing eyes",
    # 嘴巴
    "open mouth", "closed mouth", "parted lips", "wavy mouth", "clenched teeth", "teeth",
    "fang", "tongue out", ":d", ";d", ":o", ":3", ":p", ":t", ":<", "^_^", ">_<", "o_o",
    "screaming", "shouting", "biting lip", "licking lips", "gasping", "panting",
    "heavy breathing", "drooling",
    # 臉部狀態
    "blush", "blush stickers", "nose blush", "light blush", "full-face blush", "sweat",
    "sweatdrop", "flying sweatdrops", "nervous sweating",
    # 視線 / 頭部
    "looking at viewer", "looking away", "looking to the side", "looking back",
    "looking down", "looking up", "looking at another", "sideways glance", "eye contact",
    "head tilt",
]

# LLM / 使用者常寫的口語或片語 → 正規 danbooru tag
_SYNONYMS: dict[str, str] = {
    "eyes widening": "wide-eyed", "wide eyes": "wide-eyed", "widened eyes": "wide-eyed",
    "tearful eyes": "tears", "teary eyes": "tears", "tearful": "tears", "teary-eyed": "tears",
    "crying face": "crying",
    "mouth open": "open mouth", "mouth slightly open": "parted lips",
    "slightly open mouth": "parted lips", "lips parted": "parted lips",
    "glazed eyes": "empty eyes", "unfocused eyes": "empty eyes", "vacant eyes": "empty eyes",
    "glazed unfocused eyes": "empty eyes", "unfocused glazed eyes": "empty eyes",
    "hollow eyes": "empty eyes", "dead eyes": "empty eyes", "blank stare": "empty eyes",
    "blank": "expressionless", "neutral": "expressionless", "stoic": "expressionless",
    "placid": "expressionless", "calm": "expressionless",
    "smiling": "smile", "grinning": "grin", "smirking": "smirk", "frowning": "frown",
    "pouting": "pout", "blushing": "blush", "sweating": "sweat", "giggling": "laughing",
    "laugh": "laughing",
    "fearful": "scared", "afraid": "scared", "fear": "scared", "frightened": "scared",
    "panicked": "scared", "panicking": "scared", "panic": "scared",
    "tense": "nervous", "anxious": "nervous", "uneasy": "worried", "troubled": "worried",
    "concerned": "worried",
    "astonished": "surprised", "startled": "surprised", "stunned": "shocked",
    "dizzy": "dazed", "spiral eyes": "@_@", "swirly eyes": "@_@",
    "gritted teeth": "clenched teeth", "clenching teeth": "clenched teeth",
    "wincing": "pain", "grimace": "pain", "grimacing": "pain",
    "exhausted": "tired", "drowsy": "sleepy", "eyes closed": "closed eyes",
    "seductive": "seductive smile", "flirty": "seductive smile",
    "^ ^": "^_^", "spiral pupils": "@_@",
}

# 品質 / 分數詞：不該出現在每格的場景 prompt（畫風欄已經有）
_QUALITY = {
    "masterpiece", "best quality", "amazing quality", "very aesthetic", "absurdres",
    "highres", "high quality", "ultra detailed", "ultra-detailed", "newest", "8k", "4k",
}
_SCORE_RE = re.compile(r"^score_\d(_up)?$")

# 含底線的表情符號 tag 不做「底線→空白」
_EMOTICONS = {"@_@", "o_o", ">_<", "^_^", "0_0", "-_-", "._.", ";_;", "t_t", "x_x", "+_+"}
_SUFFIX_RE = re.compile(r"\s+(expression|look|expressions)$")

_SET = set(EXPRESSION_TAGS)


def normalize_tag(tag: str) -> str:
    """小寫、去空白、底線換空白（表情符號除外），並把口語片語對應成正規 tag。"""
    t = (tag or "").strip().lower()
    if not t:
        return ""
    if t not in _EMOTICONS:
        t = " ".join(t.replace("_", " ").split())
    t = _SYNONYMS.get(t, t)
    t2 = _SUFFIX_RE.sub("", t)  # "worried expression" → "worried"
    if t2 != t:
        t = _SYNONYMS.get(t2, t2)
    return t


def is_expression_tag(tag: str) -> bool:
    return normalize_tag(tag) in _SET


def is_quality_tag(tag: str) -> bool:
    t = " ".join((tag or "").strip().lower().replace("_", " ").split())
    return t in _QUALITY or bool(_SCORE_RE.match(t.replace(" ", "_")))


def clean_expression(raw: object, limit: int = 4) -> list[str]:
    """把 LLM 給的 expression（字串或陣列）整理成去重的 tag 清單。
    不在白名單的短 tag 也保留（例如自訂詞），超過三個字的句子丟掉。"""
    if isinstance(raw, (list, tuple)):
        items = [str(x) for x in raw]
    else:
        items = str(raw or "").split(",")
    out: list[str] = []
    for item in items:
        t = normalize_tag(item)
        if not t or len(t.split()) > 3 or is_quality_tag(t):
            continue
        if t not in out:
            out.append(t)
        if len(out) >= limit:
            break
    return out


def split_scene(prompt: str) -> tuple[list[str], list[str]]:
    """把場景 prompt 拆成 (場景 tag, 混進去的表情 tag)；品質詞直接丟掉。
    場景 tag 保留原文（只去頭尾空白），表情 tag 已正規化。"""
    scene: list[str] = []
    expr: list[str] = []
    for raw in (prompt or "").split(","):
        tag = raw.strip()
        if not tag:
            continue
        if is_quality_tag(tag):
            continue
        norm = normalize_tag(tag)
        if norm in _SET:
            if norm not in expr:
                expr.append(norm)
            continue
        scene.append(tag)
    return scene, expr
