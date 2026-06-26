// 把目前的分鏡＋對白氣泡合成成一張漫畫頁 PNG 並觸發下載。
// 用 <canvas> 重放與「整頁預覽」相同的版面（comic/layout.js），所以輸出與畫面一致。
// 圖片來自同源 /images，canvas 不會被污染，可正常 toDataURL。
import { computeLayout } from "./layout";

const FONT_STACK =
  '"Noto Sans CJK TC", "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", "Hiragino Sans", system-ui, sans-serif';

function loadImage(url) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = url;
  });
}

// object-fit: cover —— 置中裁切填滿矩形
function drawCover(ctx, img, x, y, w, h) {
  const ir = img.width / img.height;
  const r = w / h;
  let sx = 0,
    sy = 0,
    sw = img.width,
    sh = img.height;
  if (ir > r) {
    sw = img.height * r;
    sx = (img.width - sw) / 2;
  } else {
    sh = img.width / r;
    sy = (img.height - sh) / 2;
  }
  ctx.save();
  ctx.beginPath();
  ctx.rect(x, y, w, h);
  ctx.clip();
  ctx.drawImage(img, sx, sy, sw, sh, x, y, w, h);
  ctx.restore();
}

function roundRect(ctx, x, y, w, h, r) {
  const rr = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.arcTo(x + w, y, x + w, y + h, rr);
  ctx.arcTo(x + w, y + h, x, y + h, rr);
  ctx.arcTo(x, y + h, x, y, rr);
  ctx.arcTo(x, y, x + w, y, rr);
  ctx.closePath();
}

// 同時支援 CJK（逐字斷行）與拉丁（盡量以空白斷詞）的換行
function wrapText(ctx, text, maxW) {
  const lines = [];
  for (const para of String(text).split("\n")) {
    if (!para) {
      lines.push("");
      continue;
    }
    let line = "";
    const tokens = para.match(/\s+|[^\s]/g) || [];
    for (const tk of tokens) {
      const test = line + tk;
      if (ctx.measureText(test).width > maxW && line) {
        lines.push(line.replace(/\s+$/, ""));
        line = tk.replace(/^\s+/, "");
      } else {
        line = test;
      }
    }
    if (line.trim() || line === "") lines.push(line);
  }
  return lines.length ? lines : [""];
}

function drawBubble(ctx, b, cx, cy, cw, ch, pageW) {
  const text = (b.text || "").trim();
  if (!text && b.type !== "caption") return;
  const fs = Math.max(11, Math.round(pageW * 0.017));
  const pad = Math.round(fs * 0.6);
  const lineH = Math.round(fs * 1.32);
  const maxTextW = Math.max(40, b.w * cw - pad * 2);

  ctx.font = `${b.type === "caption" ? "" : "600 "}${fs}px ${FONT_STACK}`;
  const lines = wrapText(ctx, text, maxTextW);
  let textW = 0;
  for (const ln of lines) textW = Math.max(textW, ctx.measureText(ln).width);

  const boxW = Math.min(b.w * cw, textW + pad * 2);
  const boxH = lines.length * lineH + pad * 2;
  const centerX = cx + b.x * cw;
  const centerY = cy + b.y * ch;
  const x = centerX - boxW / 2;
  const y = centerY - boxH / 2;

  if (b.type === "caption") {
    ctx.fillStyle = "rgba(252, 247, 220, 0.95)";
    ctx.strokeStyle = "#3a3128";
    ctx.lineWidth = Math.max(1.5, pageW * 0.0016);
    ctx.fillRect(x, y, boxW, boxH);
    ctx.strokeRect(x, y, boxW, boxH);
    ctx.fillStyle = "#2a2622";
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    lines.forEach((ln, i) =>
      ctx.fillText(ln, x + pad, y + pad + lineH * (i + 0.5), boxW - pad * 2)
    );
    return;
  }

  // speech / thought 氣泡
  ctx.fillStyle = "#ffffff";
  ctx.strokeStyle = "#111111";
  ctx.lineWidth = Math.max(1.5, pageW * 0.0018);
  const radius = b.type === "thought" ? boxH / 2 : Math.round(fs * 0.7);
  roundRect(ctx, x, y, boxW, boxH, radius);
  ctx.fill();
  ctx.stroke();

  if (b.type === "speech") {
    // 朝下的小尾巴
    const tailW = Math.max(8, fs * 0.6);
    const ty = y + boxH;
    ctx.beginPath();
    ctx.moveTo(centerX - tailW / 2, ty - 1);
    ctx.lineTo(centerX + tailW / 2, ty - 1);
    ctx.lineTo(centerX - tailW * 0.1, ty + tailW * 1.4);
    ctx.closePath();
    ctx.fillStyle = "#ffffff";
    ctx.fill();
    ctx.strokeStyle = "#111111";
    ctx.beginPath();
    ctx.moveTo(centerX - tailW / 2, ty - 1);
    ctx.lineTo(centerX - tailW * 0.1, ty + tailW * 1.4);
    ctx.lineTo(centerX + tailW / 2, ty - 1);
    ctx.stroke();
  } else {
    // thought：底部兩個小泡泡
    const r1 = fs * 0.32;
    ctx.beginPath();
    ctx.arc(centerX - r1, y + boxH + r1 * 0.8, r1, 0, Math.PI * 2);
    ctx.fillStyle = "#ffffff";
    ctx.fill();
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(centerX - r1 * 2.6, y + boxH + r1 * 2.2, r1 * 0.6, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }

  ctx.fillStyle = "#111111";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  lines.forEach((ln, i) =>
    ctx.fillText(ln, centerX, y + pad + lineH * (i + 0.5), boxW - pad * 2)
  );
}

export async function exportComicPng({ panels, layout, settings, title }) {
  const usable = (panels || []).filter(Boolean);
  if (!usable.length) return;

  const aspect = (Number(settings.width) || 896) / (Number(settings.height) || 1152);
  const base = computeLayout({
    count: usable.length,
    columns: layout.columns,
    gutter: layout.gutter,
    aspect,
    pageWidth: 1000,
  });
  // 把單格放大到約 760px 寬再輸出（清晰但檔案不致過大）
  const scale = 760 / base.cellW;
  const L = computeLayout({
    count: usable.length,
    columns: layout.columns,
    gutter: layout.gutter,
    aspect,
    pageWidth: 1000 * scale,
  });

  const hasTitle = !!(title && title.trim());
  const titleH = hasTitle ? Math.round(L.pageWidth * 0.05) : 0;

  const canvas = document.createElement("canvas");
  canvas.width = Math.round(L.pageWidth);
  canvas.height = Math.round(L.pageHeight + titleH);
  const ctx = canvas.getContext("2d");

  ctx.fillStyle = layout.bg || "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  if (hasTitle) {
    ctx.fillStyle = "#111111";
    ctx.font = `700 ${Math.round(titleH * 0.55)}px ${FONT_STACK}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(title.trim(), canvas.width / 2, titleH / 2);
  }

  const imgs = await Promise.all(
    usable.map((p) => (p.image?.url ? loadImage(p.image.url) : Promise.resolve(null)))
  );

  usable.forEach((p, i) => {
    const cell = L.cells[i];
    const x = cell.x;
    const y = cell.y + titleH;
    ctx.fillStyle = "#e7e5e4";
    ctx.fillRect(x, y, cell.w, cell.h);
    if (imgs[i]) drawCover(ctx, imgs[i], x, y, cell.w, cell.h);
    ctx.lineWidth = Math.max(2, L.pageWidth * 0.0035);
    ctx.strokeStyle = "#111111";
    ctx.strokeRect(x, y, cell.w, cell.h);
    for (const b of p.bubbles || [])
      drawBubble(ctx, b, x, y, cell.w, cell.h, L.pageWidth);
  });

  const dataUrl = canvas.toDataURL("image/png");
  const a = document.createElement("a");
  a.href = dataUrl;
  a.download = `comic-${(title || "page").trim().replace(/\s+/g, "_") || "page"}.png`;
  document.body.appendChild(a);
  a.click();
  a.remove();
}
