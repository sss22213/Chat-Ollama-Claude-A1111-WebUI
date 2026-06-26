// 漫畫整頁的版面計算：給定格數、欄數、格間距、單格長寬比，
// 算出每一格在頁面座標系中的矩形。整頁預覽（HTML）與匯出（canvas）共用，
// 確保畫面與輸出 PNG 比例一致。
//
// gutter 以「1000px 頁寬」為基準，再依實際 pageWidth 等比縮放，
// 所以 pageWidth 放大時整體比例維持不變。
export function computeLayout({
  count,
  columns,
  gutter,
  aspect, // 單格 width/height
  pageWidth = 1000,
}) {
  const cols = Math.max(1, columns | 0 || 1);
  const n = Math.max(1, count | 0 || 1);
  const rows = Math.ceil(n / cols);
  const g = (gutter / 1000) * pageWidth;
  const cellW = (pageWidth - g * (cols + 1)) / cols;
  const cellH = aspect ? cellW / aspect : cellW;
  const pageHeight = g + rows * (cellH + g);

  const cells = [];
  for (let i = 0; i < n; i++) {
    const r = Math.floor(i / cols);
    const c = i % cols;
    cells.push({
      x: g + c * (cellW + g),
      y: g + r * (cellH + g),
      w: cellW,
      h: cellH,
    });
  }
  return { cols, rows, g, cellW, cellH, pageWidth, pageHeight, cells };
}
