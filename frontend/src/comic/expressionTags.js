// 表情 / 臉部狀態類 danbooru tag。與 backend/expression_tags.py 同一份清單，修改時請同步。
// 用途：組合每格提示詞時，把角色卡「外觀 / LoRA 觸發詞」裡的表情類 tag 濾掉——
// 角色 LoRA 的高頻訓練標籤常含 blush / smile / open mouth，固定帶入會蓋掉該格的表情。
const EXPRESSION_TAGS = [
  // 情緒
  "smile", "light smile", "grin", "smirk", "seductive smile", "sad smile", "laughing",
  "happy", "excited", "embarrassed", "shy", "nervous", "flustered", "worried", "sad",
  "crying", "tears", "sobbing", "scared", "terrified", "horrified", "surprised",
  "shocked", "confused", "thinking", "bored", "sleepy", "tired", "dazed", "pain",
  "angry", "furious", "annoyed", "frown", "pout", "scowl", "glaring", "serious",
  "determined", "smug", "disgust", "jealous", "expressionless",
  // 眼睛
  "closed eyes", "one eye closed", "wink", "half-closed eyes", "wide-eyed",
  "narrowed eyes", "squinting", "rolling eyes", "empty eyes", "@_@",
  "heart-shaped pupils", "sparkling eyes", "glowing eyes",
  // 嘴巴
  "open mouth", "closed mouth", "parted lips", "wavy mouth", "clenched teeth", "teeth",
  "fang", "tongue out", ":d", ";d", ":o", ":3", ":p", ":t", ":<", "^_^", ">_<", "o_o",
  "screaming", "shouting", "biting lip", "licking lips", "gasping", "panting",
  "heavy breathing", "drooling",
  // 臉部狀態
  "blush", "blush stickers", "nose blush", "light blush", "full-face blush", "sweat",
  "sweatdrop", "flying sweatdrops", "nervous sweating",
  // 視線 / 頭部
  "looking at viewer", "looking away", "looking to the side", "looking back",
  "looking down", "looking up", "looking at another", "sideways glance", "eye contact",
  "head tilt",
  // LoRA 觸發詞裡常見的成人向表情 tag（同樣不該固定每格）
  "ahegao", "naughty face", "torogao", "aroused",
];

const EMOTICONS = new Set(["@_@", "o_o", ">_<", "^_^", "0_0", "-_-", "._.", ";_;", "t_t", "x_x", "+_+"]);
const SET = new Set(EXPRESSION_TAGS);

// 小寫、底線換空白（表情符號除外）、去掉 "xxx expression" 的尾巴
export function tagKey(tag) {
  let t = (tag || "").trim().toLowerCase();
  if (!t) return "";
  if (!EMOTICONS.has(t)) t = t.replace(/_/g, " ").replace(/\s+/g, " ").trim();
  return t.replace(/\s+(expression|expressions|look)$/, "");
}

export function isExpressionTag(tag) {
  return SET.has(tagKey(tag));
}

// 依逗號拆 tag（中英文逗號皆可），去頭尾空白與空項
export function splitTags(str) {
  return (str || "")
    .split(/[,，]/)
    .map((t) => t.trim())
    .filter(Boolean);
}
