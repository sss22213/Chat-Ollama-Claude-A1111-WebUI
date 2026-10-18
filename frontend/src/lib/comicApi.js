// 漫畫工作室專用 API：寫故事、分鏡、單格重寫、看圖檢查（出圖重用 lib/api.js 的 generateImage）。

export async function generateStoryboard(payload) {
  const r = await fetch("/api/comic/storyboard", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    const detail = (await r.json().catch(() => ({}))).detail || "分鏡生成失敗";
    throw new Error(detail);
  }
  return r.json();
}

// 內建分鏡 system 範本（給「載入預設」編輯用）
export async function fetchComicSystemDefault() {
  const r = await fetch("/api/comic/system-default");
  if (!r.ok) throw new Error("無法取得預設 system");
  return (await r.json()).system || "";
}

// 只為一格重新生成場景關鍵字與表情（帶整份分鏡當前後文）
export async function regeneratePanelPrompt(payload) {
  const r = await fetch("/api/comic/panel-prompt", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    const detail = (await r.json().catch(() => ({}))).detail || "關鍵字生成失敗";
    throw new Error(detail);
  }
  return r.json();
}

async function postJson(url, payload, fallback) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    const detail = (await r.json().catch(() => ({}))).detail || fallback;
    throw new Error(detail);
  }
  return r.json();
}

// 先用劇情大綱、角色卡寫出故事（之後依故事分鏡）；帶 story＋instruction 就是改寫
export function writeComicStory(payload) {
  return postJson("/api/comic/story", payload, "故事生成失敗");
}

// 出圖後讓視覺模型看圖，確認這格有演對故事：{status: pass | fail | skipped, problems, fix, reason}
export function checkComicPanel(payload) {
  return postJson("/api/comic/check-panel", payload, "看圖檢查失敗");
}

// 角色卡的角色關鍵字 → {cards: [{name, features, outfit, scene, loras}]}
export function parseComicCharacters(payload) {
  return postJson("/api/comic/parse-characters", payload, "角色關鍵字解析失敗");
}
