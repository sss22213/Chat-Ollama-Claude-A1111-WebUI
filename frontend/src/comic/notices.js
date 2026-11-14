// 後端回傳的 notices（{code, reason, model}）→ 使用者看得懂的文字；漫畫工作室與圖片說故事共用。
// t：該頁的翻譯函式（ct / st），鍵名兩邊都有定義（saved_to_origin 等只有漫畫工作室會有）。
export function noticeText(n, t) {
  if (!n) return "";
  // 漫畫工作室自己的提示：換作品時 AI 結果存回原作品 / 已捨棄；本機修改另存成新作品
  if (n.code === "saved_to_origin") return t("noticeSavedToOrigin", { title: n.title || t("untitled") });
  if (n.code === "result_dropped") return t("noticeResultDropped");
  if (n.code === "local_copy") return t("noticeLocalCopy", { title: n.title || "" });
  if (n.code === "think_fallback") {
    const key =
      n.reason === "truncated" ? "noticeThinkTruncated" : n.reason === "long" ? "noticeThinkLong" : "noticeThinkEmpty";
    return t(key, {
      model: n.model || "",
    });
  }
  return n.code;
}
