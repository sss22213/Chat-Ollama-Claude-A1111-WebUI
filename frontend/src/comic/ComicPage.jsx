import { useRef } from "react";
import { GripVertical, X, Plus, MessageSquare } from "lucide-react";
import { useComic } from "../store/comic";
import { useCT } from "./comicI18n";
import { computeLayout } from "./layout";

const clamp01 = (v) => Math.max(0.04, Math.min(0.96, v));

// 單一氣泡：可拖曳（抓上方握把）、可即時編輯文字。樣式盡量貼近匯出 PNG。
function PageBubble({ panelId, bubble: b, cellRef }) {
  const updateBubble = useComic((s) => s.updateBubble);
  const removeBubble = useComic((s) => s.removeBubble);
  const dragging = useRef(false);

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
  const skin = isCaption
    ? "rounded-sm border border-stone-700 bg-[#fcf7dc] text-stone-800"
    : b.type === "thought"
    ? "rounded-[1.5em] border-2 border-black bg-white text-black"
    : "rounded-[0.8em] border-2 border-black bg-white text-black";

  return (
    <div
      className="group absolute z-10"
      style={{
        left: `${b.x * 100}%`,
        top: `${b.y * 100}%`,
        width: `${b.w * 100}%`,
        transform: "translate(-50%, -50%)",
      }}
    >
      <div className={`relative ${skin}`}>
        {/* 朝下的對白尾巴 */}
        {b.type === "speech" && (
          <div
            className="absolute left-1/2 h-[0.7em] w-[0.7em] -translate-x-1/2 rotate-45 border-b-2 border-r-2 border-black bg-white"
            style={{ bottom: "-0.42em" }}
          />
        )}
        {/* 工具列（hover 顯示）：拖曳握把 / 刪除 */}
        <div className="absolute -top-3 left-1/2 flex -translate-x-1/2 items-center gap-0.5 rounded-md bg-ink-900/90 px-0.5 py-0.5 opacity-0 shadow transition group-hover:opacity-100">
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
          <button
            onClick={() => removeBubble(panelId, b.id)}
            className="rounded p-0.5 text-gray-300 hover:text-red-400"
            title="✕"
          >
            <X size={12} />
          </button>
        </div>
        <textarea
          value={b.text}
          onChange={(e) => updateBubble(panelId, b.id, { text: e.target.value })}
          rows={1}
          spellCheck={false}
          className="block w-full resize-none overflow-hidden border-0 bg-transparent text-center font-semibold leading-tight outline-none"
          style={{
            fontSize: "clamp(8px, 1.7cqw, 30px)",
            padding: "0.5em 0.7em",
            fontWeight: isCaption ? 400 : 600,
            textAlign: isCaption ? "left" : "center",
          }}
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
