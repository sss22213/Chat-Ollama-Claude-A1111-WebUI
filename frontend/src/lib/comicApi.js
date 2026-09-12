// 漫畫工作室專用 API：分鏡生成（出圖重用 lib/api.js 的 generateImage）。

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
