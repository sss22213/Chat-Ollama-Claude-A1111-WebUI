import { useLayoutEffect, useRef, useState } from "react";
import { GripVertical, X, Plus, MessageSquare } from "lucide-react";
import { useComic } from "../store/comic";
import { useCT } from "./comicI18n";
import { computeLayout } from "./layout";
import {
  BUBBLE_STYLES,
  TAIL_DIRS,
  bubbleGeometry,
  bubblePaint,
  hasTail,
  styleKey,
  tailKey,
} from "./bubbleShape";

const clamp01 = (v) => Math.max(0.04, Math.min(0.96, v));

// 單一氣泡：可拖曳（抓上方握把）、可即時編輯文字、hover 工具列可換樣式與尾巴方向。
// 外形用 comic/bubbleShape.js 的 SVG path 畫（與匯出 PNG 同一套幾何），
// 大小由隱藏的鏡像 span 撐出（隨文字自動縮放高度與寬度，最寬不超過 b.w）。
function PageBubble({ panelId, bubble: b, cellRef }) {
  const ct = useCT();
  const updateBubble = useComic((s) => s.updateBubble);
  const removeBubble = useComic((s) => s.removeBubble);
  const dragging = useRef(false);
  const bodyRef = useRef(null);
  const [box, setBox] = useState({ w: 0, h: 0, fs: 14 });

  useLayoutEffect(() => {
    const el = bodyRef.current;
    if (!el) return undefined;
    const measure = () => {
      const r = el.getBoundingClientRect();
      const fs = parseFloat(getComputedStyle(el).fontSize) || 14;
      setBox((o) =>
        Math.abs(o.w - r.width) < 0.5 && Math.abs(o.h - r.height) < 0.5 && o.fs === fs
          ? o
          : { w: r.width, h: r.height, fs }
      );
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    window.addEventListener("resize", measure);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);

  const onPointerDown = (e) => {
    e.stopPropagation();
    dragging.current = true;
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
  };
  const onPointerMove = (e) => {
    if (!dragging.current || !cellRef.current) return;
    const rect = cellRef.current.getBoundingClientRect();
    updateBubble(panelId, b.id, {
      x: clamp01((e.clientX - rect.left) / rect.width),
      y: clamp01((e.clientY - rect.top) / rect.height),
    });
  };
  const onPointerUp = (e) => {
    dragging.current = false;
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
  };

  const isCaption = b.type === "caption";
  const paint = bubblePaint(b.type, box.fs);
  const g =
    box.w > 0
      ? bubbleGeometry({ style: b.type, w: box.w, h: box.h, fs: box.fs, tail: b.tail })
      : null;
  const textStyle = {
    padding: "0.5em 0.7em",
    fontWeight: isCaption ? 400 : 600,
    textAlign: isCaption ? "left" : "center",
    lineHeight: 1.25,
  };
  const selectCls =
    "h-4 max-w-[5.5rem] rounded border-0 bg-ink-800 px-0.5 text-[10px] leading-none text-gray-200 outline-none";

  return (
    <div
      className="group absolute z-10 flex justify-center"
      style={{
        left: `${b.x * 100}%`,
        top: `${b.y * 100}%`,
        width: `${b.w * 100}%`,
        transform: "translate(-50%, -50%)",
      }}
    >
      <div
        ref={bodyRef}
        className="relative grid max-w-full"
        style={{
          fontSize: "clamp(8px, 1.7cqw, 30px)",
          width: "fit-content",
          minWidth: "3em",
          color: paint.text,
        }}
      >
        {g && (
          <svg
            className="pointer-events-none absolute left-0 top-0"
            width={box.w}
            height={box.h}
            style={{ overflow: "visible" }}
            aria-hidden
          >
            <path
              d={g.path}
              fill={paint.fill}
              stroke={paint.stroke}
              strokeWidth={paint.lineWidth}
              strokeLinejoin={paint.lineJoin}
              strokeDasharray={g.dash ? g.dash.join(" ") : undefined}
            />
            {g.circles.map((c, i) => (
              <circle
                key={i}
                cx={c.x}
                cy={c.y}
                r={c.r}
                fill={paint.fill}
                stroke={paint.stroke}
                strokeWidth={paint.lineWidth}
              />
            ))}
          </svg>
        )}
        {/* 工具列（hover / 編輯中顯示）：拖曳握把 / 樣式 / 尾巴方向 / 刪除 */}
        <div
          className="absolute -top-3 left-1/2 z-10 flex -translate-x-1/2 items-center gap-0.5 rounded-md bg-ink-900/90 px-0.5 py-0.5 opacity-0 shadow transition group-hover:opacity-100 group-focus-within:opacity-100"
          style={{ fontSize: "11px" }}
        >
          <button
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            title="drag"
            className="cursor-move touch-none rounded p-0.5 text-gray-300 hover:text-white"
            style={{ touchAction: "none" }}
          >
            <GripVertical size={12} />
          </button>
          <select
            value={b.type}
            onChange={(e) => updateBubble(panelId, b.id, { type: e.target.value })}
            title={ct("bubbleStyle")}
            className={selectCls}
          >
            {BUBBLE_STYLES.map((tp) => (
              <option key={tp} value={tp}>
                {ct(styleKey(tp))}
              </option>
            ))}
          </select>
          {hasTail(b.type) && (
            <select
              value={b.tail || "down"}
              onChange={(e) => updateBubble(panelId, b.id, { tail: e.target.value })}
              title={ct("tailDir")}
              className={selectCls}
            >
              {TAIL_DIRS.map((d) => (
                <option key={d} value={d}>
                  {ct(tailKey(d))}
                </option>
              ))}
            </select>
          )}
          <button
            onClick={() => removeBubble(panelId, b.id)}
            className="rounded p-0.5 text-gray-300 hover:text-red-400"
            title={ct("deleteBubble")}
          >
            <X size={12} />
          </button>
        </div>
        {/* 鏡像 span 撐出大小；textarea 疊在同一格上 */}
        <span
          aria-hidden
          className="invisible whitespace-pre-wrap break-words [grid-area:1/1]"
          style={textStyle}
        >
          {(b.text || "") + "​"}
        </span>
        <textarea
          value={b.text}
          onChange={(e) => updateBubble(panelId, b.id, { text: e.target.value })}
          rows={1}
          spellCheck={false}
          className="relative block h-full w-full resize-none overflow-hidden border-0 bg-transparent outline-none [grid-area:1/1]"
          style={{ ...textStyle, fontSize: "1em", color: "inherit" }}
        />
      </div>
    </div>
  );
}

function PageCell({ panel, rect, pageW, pageH }) {
  const cellRef = useRef(null);
  return (
    <div
      ref={cellRef}
      className="absolute overflow-visible"
      style={{
        left: `${(rect.x / pageW) * 100}%`,
        top: `${(rect.y / pageH) * 100}%`,
        width: `${(rect.w / pageW) * 100}%`,
        height: `${(rect.h / pageH) * 100}%`,
      }}
    >
      <div className="relative h-full w-full overflow-hidden border-2 border-black bg-stone-300">
        {panel.image ? (
          <img
            src={panel.image.url}
            alt=""
            className="h-full w-full object-cover"
            draggable={false}
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-[10px] text-stone-500">
            …
          </div>
        )}
      </div>
      {(panel.bubbles || []).map((b) => (
        <PageBubble key={b.id} panelId={panel.id} bubble={b} cellRef={cellRef} />
      ))}
    </div>
  );
}

export default function ComicPage() {
  const ct = useCT();
  const panels = useComic((s) => s.panels);
  const layout = useComic((s) => s.layout);
  const settings = useComic((s) => s.settings);
  const title = useComic((s) => s.title);
  const addBubble = useComic((s) => s.addBubble);

  const aspect = (Number(settings.width) || 896) / (Number(settings.height) || 1152);
  const L = computeLayout({
    count: panels.length || 1,
    columns: layout.columns,
    gutter: layout.gutter,
    aspect,
    pageWidth: 1000,
  });

  return (
    <div className="mx-auto w-full max-w-4xl p-3">
      <p className="mb-2 text-center text-xs text-gray-500">{ct("pageHint")}</p>
      {title.trim() && (
        <h2 className="mb-2 text-center text-lg font-bold text-gray-100">
          {title}
        </h2>
      )}
      <div
        className="relative mx-auto w-full shadow-2xl"
        style={{
          aspectRatio: `${L.pageWidth} / ${L.pageHeight}`,
          background: layout.bg || "#ffffff",
          containerType: "inline-size",
        }}
      >
        {panels.map((p, i) => (
          <PageCell
            key={p.id}
            panel={p}
            rect={L.cells[i]}
            pageW={L.pageWidth}
            pageH={L.pageHeight}
          />
        ))}
      </div>

      {/* 為每格快速加氣泡（整頁不易精準點到空白格時的後備） */}
      {panels.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center justify-center gap-1.5">
          {panels.map((p, i) => (
            <div
              key={p.id}
              className="flex items-center gap-1 rounded-md border border-ink-700 bg-ink-850 px-1.5 py-1"
            >
              <span className="text-[11px] text-gray-500">
                {ct("panel", { n: i + 1 })}
              </span>
              <button
                onClick={() => addBubble(p.id, "speech")}
                title={ct("bubbleSpeech")}
                className="rounded p-0.5 text-gray-400 hover:bg-ink-750 hover:text-white"
              >
                <MessageSquare size={13} />
              </button>
              <button
                onClick={() => addBubble(p.id, "caption")}
                title={ct("bubbleCaption")}
                className="rounded p-0.5 text-gray-400 hover:bg-ink-750 hover:text-white"
              >
                <Plus size={13} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
