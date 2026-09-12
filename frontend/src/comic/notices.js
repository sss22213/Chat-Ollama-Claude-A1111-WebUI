// 後端回傳的 notices（{code, reason, model}）→ 使用者看得懂的文字；漫畫工作室與圖片說故事共用。
// t：該頁的翻譯函式（ct / st），鍵名兩邊都有定義。
export function noticeText(n, t) {
  if (!n) return "";
  if (n.code === "think_fallback") {
    return t(n.reason === "truncated" ? "noticeThinkTruncated" : "noticeThinkEmpty", {
      model: n.model || "",
    });
  }
  return n.code;
}
