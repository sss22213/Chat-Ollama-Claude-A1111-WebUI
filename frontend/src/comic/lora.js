// 解析 / 改寫 LoRA 提示詞字串裡的權重，只動 <lora:NAME:WEIGHT> 那段，
// 不影響後面的觸發詞（例如 "<lora:char:1>, blue eyes, smile"）。
// 名稱可含子資料夾（/ 或 \），但不含冒號，所以用 [^:>]+ 取名稱安全。
const LORA_RE = /(<lora:[^:>]+:)(-?\d*\.?\d+)([^>]*>)/;

export function getLoraWeight(str) {
  const m = (str || "").match(LORA_RE);
  return m ? parseFloat(m[2]) : 1;
}

export function setLoraWeight(str, weight) {
  const w = Number.isFinite(weight) ? Math.round(weight * 100) / 100 : 1;
  // 全域取代：一個角色卡通常只有一個 <lora>，但保險起見全部同步成同一權重。
  return (str || "").replace(
    /(<lora:[^:>]+:)(-?\d*\.?\d+)([^>]*>)/g,
    (_, pre, _old, post) => `${pre}${w}${post}`
  );
}
