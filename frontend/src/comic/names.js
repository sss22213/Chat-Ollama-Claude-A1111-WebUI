// 角色名比對：分鏡回傳的名字、角色卡上的名字、格子裡引用的名字，都用同一套寬鬆比對
// （忽略大小寫、空白、底線、連字號、間隔號），不會因為多打一個空白或大小寫不同就對不上。
export const nameKey = (s) =>
  String(s || "")
    .replace(/[\s_\-·•・]+/g, "")
    .toLowerCase();

export const sameName = (a, b) => {
  const ka = nameKey(a);
  return ka !== "" && ka === nameKey(b);
};

export const findCard = (cards, name) => cards.find((c) => sameName(c.name, name));
export const hasName = (list, name) => (list || []).some((n) => sameName(n, name));

// 沒填名字的角色卡在生成分鏡時自動命名，分鏡才引用得到
export const autoName = (i, lang) =>
  String(lang || "").toLowerCase().startsWith("zh") ? `角色${i}` : `Character ${i}`;
