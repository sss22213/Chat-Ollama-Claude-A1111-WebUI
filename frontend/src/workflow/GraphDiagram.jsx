// LangGraph 流程圖：inspect 給的節點 / 邊 → 由上往下分層的 SVG；給執行事件時標出執行中、跑過的節點與走過的邊。
// 排版是簡化的 Sugiyama：DFS 找出迴圈的回邊先反過來 → 最長路徑分層 → 跨層的邊插虛擬點 →
// 重心法排序減少交叉 → 往鄰居的平均位置靠攏（保持間距）。不用額外套件。
import { useMemo } from "react";

export const START = "__start__";
export const END = "__end__";

const NODE_H = 30;
const LAYER_GAP = 46;
const NODE_GAP = 28;
const DUMMY_GAP = 14;
const MARGIN = 18;
const LOOP_W = 36; // 自己連到自己的邊往右凸出的寬度
const MAX_LABEL = 28;

const isTerminal = (id) => id === START || id === END;
const shortLabel = (id) => (id === START ? "start" : id === END ? "end" : id.length > MAX_LABEL ? id.slice(0, MAX_LABEL - 1) + "…" : id);

function textWidth(s, size = 12) {
  let w = 0;
  for (const ch of s) w += ch.codePointAt(0) > 0x2e80 ? size : size * 0.6;
  return w;
}

const nodeWidth = (id) => (isTerminal(id) ? 56 : Math.max(64, Math.ceil(textWidth(shortLabel(id))) + 26));
const push = (map, k, v) => (map.get(k) || map.set(k, []).get(k)).push(v);
export const edgeKey = (source, target) => `${source}->${target}`;

export function layoutGraph(nodeIds, rawEdges) {
  const edges = (rawEdges || []).map((e, i) => ({ ...e, i }));
  const touched = new Set(edges.flatMap((e) => [e.source, e.target]));
  // 沒有任何邊連到的 start / end 不畫
  const ids = [...new Set([...(nodeIds || []), ...touched])].filter((id) => !isTerminal(id) || touched.has(id));
  ids.sort((a, b) => (a === START ? -1 : b === START ? 1 : a === END ? 1 : b === END ? -1 : 0));

  // 1. DFS：指回堆疊上節點的邊（迴圈）記成回邊；同時記下先序當各層的初始順序
  const outs = new Map(ids.map((id) => [id, []]));
  for (const e of edges) if (e.source !== e.target) outs.get(e.source).push(e);
  const mark = new Map();
  const back = new Set();
  const pre = [];
  const visit = (u) => {
    mark.set(u, 1);
    pre.push(u);
    for (const e of outs.get(u)) {
      const m = mark.get(e.target);
      if (m === 1) back.add(e.i);
      else if (!m) visit(e.target);
    }
    mark.set(u, 2);
  };
  for (const id of ids) if (!mark.get(id)) visit(id);

  // 排版方向的邊：回邊反過來，整張圖就沒有環
  const dag = edges
    .filter((e) => e.source !== e.target)
    .map((e) => (back.has(e.i) ? { from: e.target, to: e.source, e } : { from: e.source, to: e.target, e }));

  // 2. 最長路徑分層（拓撲順序）
  const rank = new Map(ids.map((id) => [id, 0]));
  const indeg = new Map(ids.map((id) => [id, 0]));
  const dagOut = new Map();
  for (const d of dag) {
    indeg.set(d.to, indeg.get(d.to) + 1);
    push(dagOut, d.from, d);
  }
  const queue = ids.filter((id) => indeg.get(id) === 0);
  while (queue.length) {
    const u = queue.shift();
    for (const d of dagOut.get(u) || []) {
      rank.set(d.to, Math.max(rank.get(d.to), rank.get(u) + 1));
      indeg.set(d.to, indeg.get(d.to) - 1);
      if (indeg.get(d.to) === 0) queue.push(d.to);
    }
  }
  if (rank.has(END) && ids.length > 1) {
    const others = ids.filter((id) => id !== END).map((id) => rank.get(id));
    rank.set(END, Math.max(rank.get(END), Math.max(...others) + 1));
  }

  // 3. 跨好幾層的邊在中間每層插一個虛擬點，邊沿著它們走、繞開其他節點
  const W = new Map(ids.map((id) => [id, nodeWidth(id)]));
  const dummy = new Set();
  const layers = [];
  const put = (id, r) => (layers[r] ||= []).push(id);
  for (const id of pre) put(id, rank.get(id));
  const chains = [];
  let dn = 0;
  for (const d of dag) {
    const path = [d.from];
    for (let r = rank.get(d.from) + 1; r < rank.get(d.to); r++) {
      const id = `\u0000${dn++}`;
      W.set(id, 0);
      rank.set(id, r);
      dummy.add(id);
      put(id, r);
      path.push(id);
    }
    path.push(d.to);
    chains.push({ e: d.e, reversed: back.has(d.e.i), path });
  }
  for (let r = 0; r < layers.length; r++) layers[r] ||= [];
  const up = new Map();
  const down = new Map();
  for (const c of chains) {
    for (let k = 0; k + 1 < c.path.length; k++) {
      push(down, c.path[k], c.path[k + 1]);
      push(up, c.path[k + 1], c.path[k]);
    }
  }

  // 4. 重心法排序：上下來回掃，留交叉最少的那次
  const pos = new Map();
  const index = () => layers.forEach((L) => L.forEach((id, i) => pos.set(id, i)));
  index();
  const crossings = () => {
    let n = 0;
    for (let r = 0; r + 1 < layers.length; r++) {
      const segs = [];
      for (const u of layers[r]) for (const v of down.get(u) || []) segs.push([pos.get(u), pos.get(v)]);
      for (let a = 0; a < segs.length; a++)
        for (let b = a + 1; b < segs.length; b++) if ((segs[a][0] - segs[b][0]) * (segs[a][1] - segs[b][1]) < 0) n++;
    }
    return n;
  };
  const sortLayer = (L, nb) => {
    const bc = new Map(
      L.map((id) => {
        const ns = nb.get(id) || [];
        return [id, ns.length ? ns.reduce((s, v) => s + pos.get(v), 0) / ns.length : pos.get(id)];
      })
    );
    L.sort((a, b) => bc.get(a) - bc.get(b));
    L.forEach((id, i) => pos.set(id, i));
  };
  let best = layers.map((L) => [...L]);
  let bestN = crossings();
  for (let it = 0; it < 8 && bestN > 0; it++) {
    if (it % 2 === 0) for (let r = 1; r < layers.length; r++) sortLayer(layers[r], up);
    else for (let r = layers.length - 2; r >= 0; r--) sortLayer(layers[r], down);
    const n = crossings();
    if (n < bestN) {
      bestN = n;
      best = layers.map((L) => [...L]);
    }
  }
  best.forEach((L, r) => (layers[r] = L));
  index();

  // 5. 水平座標：每個點往相鄰層鄰居的平均位置靠，但同層保持順序與間距
  //   （從左往右推、從右往左推各算一次再平均，兩邊都滿足間距，平均也滿足）
  const x = new Map();
  const sep = (a, b) => W.get(a) / 2 + W.get(b) / 2 + (dummy.has(a) || dummy.has(b) ? DUMMY_GAP : NODE_GAP);
  for (const L of layers) L.forEach((id, i) => x.set(id, i ? x.get(L[i - 1]) + sep(L[i - 1], id) : 0));
  const place = (L, want) => {
    const n = L.length;
    const left = [];
    const right = [];
    for (let i = 0; i < n; i++) left[i] = i ? Math.max(want[i], left[i - 1] + sep(L[i - 1], L[i])) : want[i];
    for (let i = n - 1; i >= 0; i--) right[i] = i < n - 1 ? Math.min(want[i], right[i + 1] - sep(L[i], L[i + 1])) : want[i];
    L.forEach((id, i) => x.set(id, (left[i] + right[i]) / 2));
  };
  const avg = (list, fallback) => (list?.length ? list.reduce((s, v) => s + x.get(v), 0) / list.length : fallback);
  for (let it = 0; it < 8; it++) {
    const downward = it % 2 === 0;
    const order = layers.map((_, r) => (downward ? r : layers.length - 1 - r));
    for (const r of order) place(layers[r], layers[r].map((id) => avg((downward ? up : down).get(id), x.get(id))));
  }
  for (const L of layers) place(L, L.map((id) => avg([...(up.get(id) || []), ...(down.get(id) || [])], x.get(id))));

  const selfLoops = edges.filter((e) => e.source === e.target && x.has(e.source));
  const loopNodes = new Set(selfLoops.map((e) => e.source));
  let minX = Infinity;
  let maxX = -Infinity;
  for (const [id, cx] of x) {
    minX = Math.min(minX, cx - W.get(id) / 2);
    maxX = Math.max(maxX, cx + W.get(id) / 2 + (loopNodes.has(id) ? LOOP_W : 0));
  }
  const dx = MARGIN - minX;
  const X = (id) => x.get(id) + dx;
  const top = (id) => MARGIN + rank.get(id) * (NODE_H + LAYER_GAP);

  // 6. 連接點：同一個節點上下各有好幾條邊時沿著寬度分開，箭頭不疊在一起
  const outPorts = new Map();
  const inPorts = new Map();
  for (const c of chains) {
    push(outPorts, c.path[0], c);
    push(inPorts, c.path[c.path.length - 1], c);
  }
  const portX = new Map(); // `${chain idx}:out|in` → x
  const spread = (id, list, end) => {
    const other = (c) => X(end === "out" ? c.path[1] : c.path[c.path.length - 2]);
    const sorted = [...list].sort((a, b) => other(a) - other(b));
    const n = sorted.length;
    const span = Math.min(W.get(id) * 0.6, (n - 1) * 14);
    sorted.forEach((c, k) => portX.set(`${c.e.i}:${end}`, X(id) + (n > 1 ? -span / 2 + (span * k) / (n - 1) : 0)));
  };
  for (const [id, list] of outPorts) spread(id, list, "out");
  for (const [id, list] of inPorts) spread(id, list, "in");

  // 7. 邊的路徑：節點底部 → 虛擬點（在該層裡直直穿過）→ 節點頂部；回邊整條反過來畫，箭頭指回原本的目標
  const curve = (pts) => {
    let d = `M${pts[0].x},${pts[0].y}`;
    for (let k = 1; k < pts.length; k++) {
      const a = pts[k - 1];
      const b = pts[k];
      if (a.x === b.x && a.straight && b.straight) d += ` L${b.x},${b.y}`;
      else {
        const h = (b.y - a.y) / 2;
        d += ` C${a.x},${a.y + h} ${b.x},${b.y - h} ${b.x},${b.y}`;
      }
    }
    return d;
  };
  const outEdges = chains.map((c) => {
    const last = c.path.length - 1;
    let pts = [{ x: portX.get(`${c.e.i}:out`), y: top(c.path[0]) + NODE_H }];
    for (const id of c.path.slice(1, last)) {
      pts.push({ x: X(id), y: top(id), straight: true }, { x: X(id), y: top(id) + NODE_H, straight: true });
    }
    pts.push({ x: portX.get(`${c.e.i}:in`), y: top(c.path[last]) });
    if (c.reversed) pts = pts.reverse();
    return { ...edgeBase(c.e), d: curve(pts), seg: [pts[0], pts[1]] };
  });
  // 標籤放在離開起點後的第一段（層與層之間沒有節點的地方），靠近做判斷的那個節點；
  // 沿著那段曲線找不會壓到其他標籤或節點的位置（同一個節點分出去的好幾條條件邊）
  const along = ([a, b], t) => {
    const h = (b.y - a.y) / 2;
    const u = 1 - t;
    return {
      x: u * u * u * a.x + 3 * u * u * t * a.x + 3 * u * t * t * b.x + t * t * t * b.x,
      y: u * u * u * a.y + 3 * u * u * t * (a.y + h) + 3 * u * t * t * (b.y - h) + t * t * t * b.y,
    };
  };
  const taken = ids.map((id) => ({ x: X(id) - W.get(id) / 2, y: top(id), w: W.get(id), h: NODE_H }));
  const overlaps = (r) => taken.some((o) => r.x < o.x + o.w && o.x < r.x + r.w && r.y < o.y + o.h && o.y < r.y + r.h);
  const labelled = [...outEdges.filter((e) => e.label), ...outEdges.filter((e) => !e.label)];
  for (const e of labelled) {
    const w = textWidth(e.label ? `${e.label} ×9` : "×9", 10) + 8;
    const box = (p) => ({ x: p.x - w / 2, y: p.y - 7, w, h: 14 });
    // 先放上半段、再下半段：同一段裡兩個標籤會上下錯開
    const p = [0.25, 0.75, 0.5, 0.12, 0.9].map((t) => along(e.seg, t)).find((q) => !overlaps(box(q))) || along(e.seg, 0.5);
    e.lx = p.x;
    e.ly = p.y;
    if (e.label) taken.push(box(p));
  }
  for (const e of selfLoops) {
    const xr = X(e.source) + W.get(e.source) / 2;
    const yc = top(e.source) + NODE_H / 2;
    outEdges.push({
      ...edgeBase(e),
      d: `M${xr},${yc - 7} C${xr + LOOP_W},${yc - 26} ${xr + LOOP_W},${yc + 26} ${xr + 2},${yc + 7}`,
      lx: xr + LOOP_W - 6,
      ly: yc,
    });
  }

  const nodes = ids.map((id) => ({ id, label: shortLabel(id), x: X(id), y: top(id), w: W.get(id), terminal: isTerminal(id) }));
  const height = MARGIN * 2 + (Math.max(...ids.map((id) => rank.get(id)), 0) + 1) * (NODE_H + LAYER_GAP) - LAYER_GAP;
  // 邊的標籤可能超出節點的範圍：寬度算進去，整張圖往右移（offsetX）
  let lo = 0;
  let hi = maxX - minX + MARGIN * 2;
  for (const e of outEdges) {
    if (!e.label) continue;
    const half = textWidth(`${e.label} ×9`, 10) / 2 + 8;
    lo = Math.min(lo, e.lx - half);
    hi = Math.max(hi, e.lx + half);
  }
  return { nodes, edges: outEdges, width: Math.ceil(hi - lo), height, offsetX: -lo };
}

function edgeBase(e) {
  return { key: edgeKey(e.source, e.target), id: e.i, source: e.source, target: e.target, conditional: !!e.conditional, label: e.label || "" };
}

// 執行事件 → 每個節點跑了幾次、現在的狀態、每條邊走過幾次。
// task = 節點開始、node = 節點完成。LangGraph 一步（superstep）裡的節點都完成後下一步才開始，
// 所以一個節點開始時，觸發它的就是上一批完成、而且有邊連過來的節點（匯合時會有好幾條）。
export function traceRun(events, edges, status) {
  const has = new Set((edges || []).map((e) => edgeKey(e.source, e.target)));
  const visits = {};
  const open = {};
  const edgeHits = {};
  const done = [START];
  let batch = [START]; // 上一批完成的節點
  let finishing = []; // 這一批目前完成的
  let lastWasNode = false;
  let sawTask = false;
  let waiting = ""; // 停在 interrupt、等人回覆的節點
  const rerun = new Set(); // 回覆後會從頭重跑的節點（那次開始不算重新走一次邊）
  let signal = ""; // 舊版 langgraph 沒有 task 事件時，用節點裡最後的動靜（LLM、生圖…）當作執行中
  const add = (k) => (edgeHits[k] = (edgeHits[k] || 0) + 1);
  // 從 from 裡有邊連到 to 的都算走過；都沒有就往回找最近完成、有邊連過來的節點
  const hit = (from, to) => {
    const linked = from.filter((s) => has.has(edgeKey(s, to)));
    if (linked.length) return linked.forEach((s) => add(edgeKey(s, to)));
    for (let i = done.length - 1; i >= Math.max(0, done.length - 60); i--) {
      if (has.has(edgeKey(done[i], to))) return add(edgeKey(done[i], to));
    }
  };
  for (const e of events || []) {
    if (e.ns || !e.node) continue;
    if (e.type === "interrupt") {
      waiting = e.node;
      if (open[e.node] > 0) open[e.node] -= 1;
      rerun.add(e.node);
    } else if (e.type === "resume") {
      waiting = "";
    } else if (e.type === "task") {
      sawTask = true;
      if (lastWasNode) {
        batch = finishing;
        finishing = [];
        lastWasNode = false;
      }
      open[e.node] = (open[e.node] || 0) + 1;
      if (rerun.has(e.node)) rerun.delete(e.node);
      else hit(batch, e.node);
    } else if (e.type === "node") {
      if (open[e.node] > 0) open[e.node] -= 1;
      else hit([], e.node);
      visits[e.node] = (visits[e.node] || 0) + 1;
      done.push(e.node);
      finishing.push(e.node);
      lastWasNode = true;
      if (signal === e.node) signal = "";
    } else {
      signal = e.node;
    }
  }
  if (done.length > 1 || sawTask) visits[START] = 1;
  if (status === "done") {
    hit(lastWasNode ? finishing : batch, END);
    visits[END] = 1;
  }
  const state = {};
  const left = Object.entries(open).filter(([, n]) => n > 0).map(([id]) => id);
  if (!sawTask && signal && status === "running") left.push(signal);
  for (const id of left) state[id] = status === "running" ? "active" : status === "error" ? "failed" : "paused";
  if (waiting) state[waiting] = status === "running" ? "waiting" : "paused";
  return { visits, state, edgeHits };
}

const NODE_STYLE = {
  idle: { fill: "#1f1f1f", stroke: "#3a3a3a", text: "#e5e7eb" },
  visited: { fill: "rgba(16,185,129,0.12)", stroke: "#34d399", text: "#ecfdf5" },
  active: { fill: "rgba(14,165,233,0.18)", stroke: "#38bdf8", text: "#f0f9ff" },
  failed: { fill: "rgba(239,68,68,0.15)", stroke: "#f87171", text: "#fef2f2" },
  waiting: { fill: "rgba(245,158,11,0.18)", stroke: "#fbbf24", text: "#fffbeb" },
  paused: { fill: "rgba(245,158,11,0.10)", stroke: "#b45309", text: "#fde68a" },
  terminal: { fill: "#2e2e2e", stroke: "#3a3a3a", text: "#9ca3af" },
};
const EDGE_IDLE = "#6b7280";
const EDGE_HIT = "#818cf8";

export default function GraphDiagram({ nodes, edges, events, status, selected, onSelect }) {
  const layout = useMemo(() => layoutGraph(nodes, edges), [nodes, edges]);
  const trace = useMemo(() => traceRun(events, edges, status), [events, edges, status]);
  const style = (n) => {
    const s = trace.state[n.id];
    if (s) return NODE_STYLE[s];
    if (trace.visits[n.id]) return NODE_STYLE.visited;
    return n.terminal ? NODE_STYLE.terminal : NODE_STYLE.idle;
  };

  return (
    <svg
      viewBox={`0 0 ${layout.width} ${layout.height}`}
      width={layout.width}
      style={{ maxWidth: "100%", height: "auto" }}
      className="mx-auto block select-none"
      data-testid="wf-diagram"
    >
      <defs>
        {[
          ["wf-arrow", EDGE_IDLE],
          ["wf-arrow-hit", EDGE_HIT],
        ].map(([id, color]) => (
          <marker key={id} id={id} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill={color} />
          </marker>
        ))}
      </defs>
      <g transform={`translate(${layout.offsetX},0)`}>
        {layout.edges.map((e) => {
          const n = trace.edgeHits[e.key] || 0;
          const badge = [e.label, n > 1 ? `×${n}` : ""].filter(Boolean).join(" ");
          return (
            <g key={e.id} data-edge={e.key} data-hits={n}>
              <path
                d={e.d}
                fill="none"
                stroke={n ? EDGE_HIT : EDGE_IDLE}
                strokeWidth={n ? 2 : 1.3}
                strokeDasharray={e.conditional ? "5 4" : undefined}
                markerEnd={`url(#${n ? "wf-arrow-hit" : "wf-arrow"})`}
              />
              {badge && (
                <g transform={`translate(${e.lx},${e.ly})`}>
                  <rect x={-textWidth(badge, 10) / 2 - 4} y={-8} width={textWidth(badge, 10) + 8} height={16} rx={4} fill="#171717" />
                  <text textAnchor="middle" dominantBaseline="central" fontSize="10" fill={n ? "#c7d2fe" : "#9ca3af"}>
                    {badge}
                  </text>
                </g>
              )}
            </g>
          );
        })}
        {layout.nodes.map((n) => {
          const s = style(n);
          const visits = trace.visits[n.id] || 0;
          const state = trace.state[n.id] || (visits ? "visited" : "idle");
          const left = n.x - n.w / 2;
          const clickable = !n.terminal && onSelect;
          return (
            <g
              key={n.id}
              data-node={n.id}
              data-state={state}
              onClick={clickable ? () => onSelect(n.id === selected ? "" : n.id) : undefined}
              style={clickable ? { cursor: "pointer" } : undefined}
            >
              <title>{n.terminal ? n.label : visits ? `${n.id} · ×${visits}` : n.id}</title>
              {n.id === selected && (
                <rect x={left - 4} y={n.y - 4} width={n.w + 8} height={NODE_H + 8} rx={10} fill="none" stroke="#a5b4fc" strokeWidth={1.5} strokeDasharray="3 3" />
              )}
              {(state === "active" || state === "waiting") && (
                <rect
                  x={left - 3}
                  y={n.y - 3}
                  width={n.w + 6}
                  height={NODE_H + 6}
                  rx={9}
                  fill="none"
                  stroke={state === "active" ? "#38bdf8" : "#fbbf24"}
                  strokeWidth={3}
                  className="animate-pulse"
                />
              )}
              <rect x={left} y={n.y} width={n.w} height={NODE_H} rx={n.terminal ? NODE_H / 2 : 7} fill={s.fill} stroke={s.stroke} strokeWidth={1.5} />
              <text x={n.x} y={n.y + NODE_H / 2} textAnchor="middle" dominantBaseline="central" fontSize={n.terminal ? 11 : 12} fill={s.text}>
                {n.label}
              </text>
              {visits > 1 && (
                <g transform={`translate(${left + n.w},${n.y})`}>
                  <rect x={-12} y={-8} width={24} height={15} rx={7} fill="#065f46" stroke="#34d399" strokeWidth={1} />
                  <text textAnchor="middle" dominantBaseline="central" y={-0.5} fontSize="9.5" fill="#ecfdf5">
                    ×{visits}
                  </text>
                </g>
              )}
            </g>
          );
        })}
      </g>
    </svg>
  );
}
