// 圖片說故事 API：上傳圖片（base64）→ LLM 生成故事或漫畫腳本。

export async function generateFromImage(payload) {
  const r = await fetch("/api/story/from-image", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    const detail = (await r.json().catch(() => ({}))).detail || "生成失敗";
    throw new Error(detail);
  }
  return r.json();
}
