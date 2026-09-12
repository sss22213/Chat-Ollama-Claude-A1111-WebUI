// 氣泡形狀：整頁預覽（SVG path）與匯出 PNG（canvas Path2D）共用同一套幾何，
// 所以畫面上看到的樣式、尾巴方向，匯出後一模一樣。
//
// 座標以氣泡本體（文字框）的左上角為原點、單位 px；尾巴 / 尖刺會超出本體範圍。
// fs = 該氣泡的字級，所有比例（圓角、尾巴長度、尖刺）都以它為基準，縮放不走樣。

export const BUBBLE_STYLES = ["speech", "rect", "shout", "whisper", "thought", "caption"];
export const TAIL_DIRS = [
  "none",
  "down",
  "down-left",
  "down-right",
  "left",
  "right",
  "up",
  "up-left",
  "up-right",
];

export const hasTail = (style) => style !== "caption";
export const defaultTail = (style) => (hasTail(style) ? "down" : "none");

const DIR_VEC = {
  none: [0, 0],
  up: [0, -1],
  down: [0, 1],
  left: [-1, 0],
  right: [1, 0],
  "up-left": [-1, -1],
  "up-right": [1, -1],
  "down-left": [-1, 1],
  "down-right": [1, 1],
};

// 圓角矩形的頂點（順時針，從頂邊左端開始）
function roundedRectPoints(w, h, r, steps = 6) {
  r = Math.max(0, Math.min(r, w / 2, h / 2));
  if (r < 0.5) {
    return [
      [0, 0],
      [w, 0],
      [w, h],
      [0, h],
    ];
  }
  const pts = [];
  const arc = (cx, cy, a0, a1) => {
    for (let i = 0; i <= steps; i++) {
      const a = a0 + ((a1 - a0) * i) / steps;
      pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
    }
  };
  arc(w - r, r, -Math.PI / 2, 0); // 右上
  arc(w - r, h - r, 0, Math.PI / 2); // 右下
  arc(r, h - r, Math.PI / 2, Math.PI); // 左下
  arc(r, r, Math.PI, 1.5 * Math.PI); // 左上
  return pts;
}

// 封閉折線工具：弧長定位、射線交點、區間頂點
function polyline(pts) {
  const n = pts.length;
  const cum = [0];
  for (let i = 0; i < n; i++) {
    const [x0, y0] = pts[i];
    const [x1, y1] = pts[(i + 1) % n];
    cum.push(cum[i] + Math.hypot(x1 - x0, y1 - y0));
  }
  const total = cum[n] || 1;
  const wrap = (s) => ((s % total) + total) % total;

  const pointAt = (s) => {
    s = wrap(s);
    let i = 0;
    while (i < n - 1 && cum[i + 1] < s) i++;
    const [x0, y0] = pts[i];
    const [x1, y1] = pts[(i + 1) % n];
    const L = cum[i + 1] - cum[i] || 1;
    const u = (s - cum[i]) / L;
    return [x0 + (x1 - x0) * u, y0 + (y1 - y0) * u];
  };

  // 從 (cx,cy) 往 (dx,dy) 射出，與外框的交點（含弧長位置）
  const rayHit = (cx, cy, dx, dy) => {
    for (let i = 0; i < n; i++) {
      const [x0, y0] = pts[i];
      const [x1, y1] = pts[(i + 1) % n];
      const ex = x1 - x0;
      const ey = y1 - y0;
      const den = dx * ey - dy * ex;
      if (Math.abs(den) < 1e-9) continue;
      const px = x0 - cx;
      const py = y0 - cy;
      const t = (px * ey - py * ex) / den;
      const u = (px * dy - py * dx) / den;
      if (t > 0 && u >= 0 && u <= 1) {
        return { s: cum[i] + u * (cum[i + 1] - cum[i]), x: cx + dx * t, y: cy + dy * t };
      }
    }
    return null;
  };

  // 弧長 sFrom → sTo（順時針、可跨越起點）之間的原始頂點
  const between = (sFrom, sTo) => {
    const span = wrap(sTo - sFrom);
    const out = [];
    for (let i = 0; i < n; i++) {
      const rel = wrap(cum[i] - sFrom);
      if (rel > 0 && rel < span) out.push({ rel, p: pts[i] });
    }
    out.sort((a, b) => a.rel - b.rel);
    return out.map((o) => o.p);
  };

  return { total, pointAt, rayHit, between };
}

// 在外框上接一根三角尾巴（單一封閉多邊形，外框線不會穿過尾巴根部）
function withTail(pts, { cx, cy, dx, dy, tw, len, curve }) {
  const pl = polyline(pts);
  const hit = pl.rayHit(cx, cy, dx, dy);
  if (!hit) return pts;
  const m = Math.hypot(dx, dy) || 1;
  const ux = dx / m;
  const uy = dy / m;
  const s0 = hit.s - tw / 2;
  const s1 = hit.s + tw / 2;
  // 尖端沿方向外推，再往側邊偏一點，比較像手繪
  const tip = [hit.x + ux * len - uy * len * curve, hit.y + uy * len + ux * len * curve];
  return [pl.pointAt(s1), ...pl.between(s1, s0), pl.pointAt(s0), tip];
}

// 吶喊：外框加一圈長短交錯的尖刺；正對尾巴方向的那根拉長當尾巴
function burst(w, h, { fs, cx, cy, dx, dy, len }) {
  const pl = polyline(roundedRectPoints(w, h, Math.min(w, h) * 0.25, 4));
  const n = Math.max(10, Math.round(pl.total / (fs * 1.1)));
  const hit = dx || dy ? pl.rayHit(cx, cy, dx, dy) : null;
  const phase = hit ? hit.s : 0;
  const out = [];
  for (let i = 0; i < n; i++) {
    const [ox, oy] = pl.pointAt(phase + (i / n) * pl.total);
    const [ix, iy] = pl.pointAt(phase + ((i + 0.5) / n) * pl.total);
    const nx = ox - cx;
    const ny = oy - cy;
    const nm = Math.hypot(nx, ny) || 1;
    const spike = fs * (i % 2 ? 0.75 : 0.45);
    out.push([ox + (nx / nm) * spike, oy + (ny / nm) * spike]);
    const inx = ix - cx;
    const iny = iy - cy;
    const im = Math.hypot(inx, iny) || 1;
    out.push([ix - (inx / im) * fs * 0.12, iy - (iny / im) * fs * 0.12]);
  }
  if (hit) {
    const m = Math.hypot(dx, dy) || 1;
    out[0] = [hit.x + (dx / m) * len * 1.4, hit.y + (dy / m) * len * 1.4];
  }
  return out;
}

/**
 * @param {{style:string, w:number, h:number, fs:number, tail?:string}} o
 * @returns {{path:string, circles:{x:number,y:number,r:number}[], dash:number[]|null, extent:number}}
 *   path    SVG path（可直接餵 <path d> 或 new Path2D）
 *   circles 心聲氣泡的尾巴小圓
 *   dash    悄悄話的虛線樣式
 *   extent  形狀最多超出本體多少 px（預覽 svg 要留的邊）
 */
export function bubbleGeometry({ style, w, h, fs, tail }) {
  const s = BUBBLE_STYLES.includes(style) ? style : "speech";
  const dir = hasTail(s) ? (TAIL_DIRS.includes(tail) ? tail : "down") : "none";
  const [dx, dy] = DIR_VEC[dir];
  const cx = w / 2;
  const cy = h / 2;
  const len = fs * 1.3;
  const tw = fs * 0.9;
  let pts;
  let circles = [];
  let dash = null;

  if (s === "caption") {
    pts = roundedRectPoints(w, h, 0);
  } else if (s === "shout") {
    pts = burst(w, h, { fs, cx, cy, dx, dy, len });
  } else if (s === "thought") {
    pts = roundedRectPoints(w, h, Math.min(w, h) / 2);
    if (dx || dy) {
      const hit = polyline(pts).rayHit(cx, cy, dx, dy);
      if (hit) {
        const m = Math.hypot(dx, dy) || 1;
        const ux = dx / m;
        const uy = dy / m;
        circles = [
          { x: hit.x + ux * fs * 0.6, y: hit.y + uy * fs * 0.6, r: fs * 0.3 },
          { x: hit.x + ux * fs * 1.25 - uy * fs * 0.15, y: hit.y + uy * fs * 1.25 + ux * fs * 0.15, r: fs * 0.17 },
        ];
      }
    }
  } else {
    const r = s === "rect" ? fs * 0.15 : fs * 0.7;
    pts = roundedRectPoints(w, h, r);
    if (dx || dy) pts = withTail(pts, { cx, cy, dx, dy, tw, len, curve: 0.2 });
    if (s === "whisper") dash = [fs * 0.35, fs * 0.25];
  }

  const path = "M" + pts.map(([x, y]) => `${x.toFixed(1)} ${y.toFixed(1)}`).join("L") + "Z";
  return { path, circles, dash, extent: len * 1.5 + fs };
}

// 兩邊共用的顏色 / 線寬
export function bubblePaint(style, fs) {
  const caption = style === "caption";
  return {
    fill: caption ? "rgba(252, 247, 220, 0.95)" : "#ffffff",
    stroke: caption ? "#3a3128" : "#111111",
    text: caption ? "#2a2622" : "#111111",
    lineWidth: Math.max(1.5, fs * 0.1),
    lineJoin: style === "shout" ? "miter" : "round",
  };
}

// i18n key：樣式 / 方向 → comicI18n 的鍵名
export const styleKey = (style) => "bubble" + style.charAt(0).toUpperCase() + style.slice(1);
export const tailKey = (dir) =>
  "tail" + (dir || "down").split("-").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join("");
