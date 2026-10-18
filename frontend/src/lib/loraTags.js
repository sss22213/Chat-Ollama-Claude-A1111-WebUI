// 文字裡的 <lora:名稱:…>：改名後換成新名稱（跟後端 lora_refs.rename_in_text 同一套規則：名稱完全相同才換）
const TAG_RE = /<(lora|lyco):([^:>]+)(?=[:>])/gi;

export function renameLoraTags(text, mapping) {
  if (typeof text !== "string" || !text.includes("<")) return text;
  return text.replace(TAG_RE, (all, kind, name) => {
    const to = mapping[name.trim()];
    return to ? `<${kind}:${to}` : all;
  });
}

// 物件 / 陣列裡所有字串都換；沒改到就回原物件（方便判斷要不要 set）
export function deepRenameLoraTags(value, mapping) {
  if (typeof value === "string") return renameLoraTags(value, mapping);
  if (Array.isArray(value)) {
    const out = value.map((v) => deepRenameLoraTags(v, mapping));
    return out.some((v, i) => v !== value[i]) ? out : value;
  }
  if (value && typeof value === "object") {
    let changed = false;
    const out = {};
    for (const [k, v] of Object.entries(value)) {
      out[k] = deepRenameLoraTags(v, mapping);
      if (out[k] !== v) changed = true;
    }
    return changed ? out : value;
  }
  return value;
}
