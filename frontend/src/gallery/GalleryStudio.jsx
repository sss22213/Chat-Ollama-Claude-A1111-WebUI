import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  ArchiveRestore,
  ArrowLeft,
  BookOpen,
  CheckSquare,
  FolderOpen,
  GalleryThumbnails,
  ImageOff,
  Link2,
  Loader2,
  RefreshCw,
  Search,
  Square,
  Trash2,
  Undo2,
  Upload,
  X,
} from "lucide-react";
import { useGallery } from "../store/gallery";
import { formatBytes, thumbUrl, trashThumbUrl } from "../lib/galleryApi";
import { useGT, useLang } from "./galleryI18n";
import ImageDetail from "./ImageDetail";
import { useConfirmDelete } from "./useConfirmDelete";
import { navigate } from "../Root";

const btnCls =
  "flex shrink-0 items-center gap-1.5 rounded-lg border border-ink-600 px-2.5 py-1.5 text-sm text-gray-300 hover:bg-ink-750 disabled:opacity-40";
const selectCls =
  "min-w-0 rounded-lg border border-ink-600 bg-ink-800 px-2 py-1.5 text-sm outline-none focus:border-ink-500";
const GRID = {
  s: "grid-cols-[repeat(auto-fill,minmax(104px,1fr))]",
  m: "grid-cols-[repeat(auto-fill,minmax(160px,1fr))]",
  l: "grid-cols-[repeat(auto-fill,minmax(250px,1fr))]",
};
const THUMB = { s: 256, m: 384, l: 512 };

export default function GalleryStudio() {
  const view = useGallery((s) => s.view);
  const load = useGallery((s) => s.load);
  const loadTrash = useGallery((s) => s.loadTrash);
  const detail = useGallery((s) => s.detail);

  useEffect(() => {
    if (useGallery.getState().view === "trash") loadTrash();
    else load();
  }, [load, loadTrash]);

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-ink-900 text-[#ececec]" data-testid="gallery">
      <Header />
      {view === "trash" ? <TrashView /> : <GridView />}
      {detail && <ImageDetail />}
    </div>
  );
}

function Header() {
  const gt = useGT();
  const view = useGallery((s) => s.view);
  const setView = useGallery((s) => s.setView);
  const trashCount = useGallery((s) => s.trashCount);
  const counts = useGallery((s) => s.counts);
  const totalBytes = useGallery((s) => s.totalBytes);
  const selecting = useGallery((s) => s.selecting);
  const setSelecting = useGallery((s) => s.setSelecting);
  const loading = useGallery((s) => s.loading);
  const load = useGallery((s) => s.load);
  return (
    <header className="flex items-center gap-1.5 border-b border-ink-700 bg-ink-850 px-2 py-2 sm:gap-2 sm:px-3">
      <button
        onClick={() => (view === "trash" ? setView("grid") : navigate(""))}
        title={view === "trash" ? gt("backToGallery") : gt("backToChat")}
        className="shrink-0 rounded-lg p-2 text-gray-400 hover:bg-ink-750"
        data-testid="gal-back"
      >
        <ArrowLeft size={18} />
      </button>
      <h1 className="flex min-w-0 items-center gap-1.5 text-sm font-semibold">
        {view === "trash" ? <Trash2 size={17} /> : <GalleryThumbnails size={17} />}
        <span className="truncate">{view === "trash" ? gt("trash") : gt("title")}</span>
      </h1>
      {view === "grid" && counts.all != null && (
        <span className="hidden truncate text-xs text-gray-500 sm:inline" data-testid="gal-stats">
          {gt("stats", { n: counts.all, size: formatBytes(totalBytes) })}
        </span>
      )}
      <div className="flex-1" />
      {view === "grid" && (
        <>
          <button onClick={() => load()} title="↻" className="shrink-0 rounded-lg p-2 text-gray-400 hover:bg-ink-750">
            <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
          </button>
          <button
            onClick={() => setSelecting(!selecting)}
            className={`${btnCls} ${selecting ? "border-emerald-600/60 bg-emerald-600/15 text-emerald-300" : ""}`}
            data-testid="gal-select"
          >
            {selecting ? <X size={15} /> : <CheckSquare size={15} />}
            <span className="hidden sm:inline">{selecting ? gt("cancel") : gt("select")}</span>
          </button>
          <button onClick={() => setView("trash")} className={btnCls} data-testid="gal-open-trash" title={gt("trash")}>
            <Trash2 size={15} />
            <span className="hidden sm:inline">{gt("trash")}</span>
            {trashCount > 0 && (
              <span className="rounded bg-ink-700 px-1.5 text-[11px] text-gray-300" data-testid="gal-trash-count">
                {trashCount}
              </span>
            )}
          </button>
        </>
      )}
    </header>
  );
}

function Toolbar() {
  const gt = useGT();
  const g = useGallery();
  const [q, setQ] = useState(g.q);
  // 打字停 300ms 才查
  useEffect(() => {
    if (q === useGallery.getState().q) return;
    const id = setTimeout(() => useGallery.getState().setFilter({ q }), 300);
    return () => clearTimeout(id);
  }, [q]);
  const folderLabel = (f) =>
    `${f.path}${f.current ? `（${gt("folderCurrent")}）` : f.default ? `（${gt("folderDefault")}）` : ""}${
      f.exists ? "" : `（${gt("folderMissing")}）`
    }`;
  const kinds = ["", "generated", "comic", "upload"];
  return (
    <div className="space-y-2 border-b border-ink-700 px-2 py-2 sm:px-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[12rem] flex-1">
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={gt("searchPh")}
            data-testid="gal-search"
            className="w-full rounded-lg border border-ink-600 bg-ink-800 py-1.5 pl-8 pr-7 text-sm outline-none focus:border-ink-500"
          />
          {q && (
            <button onClick={() => setQ("")} className="absolute right-1.5 top-1/2 -translate-y-1/2 p-0.5 text-gray-500 hover:text-gray-300">
              <X size={14} />
            </button>
          )}
        </div>
        {g.folders.length > 1 && (
          <label className="flex min-w-0 max-w-full items-center gap-1 text-gray-400" title={gt("folder")}>
            <FolderOpen size={15} className="shrink-0" />
            <select
              value={g.folder || g.currentFolder}
              onChange={(e) => {
                const f = g.folders.find((x) => x.path === e.target.value);
                g.setFilter({ folder: f?.current ? "" : e.target.value });
              }}
              className={`${selectCls} max-w-[60vw] sm:max-w-[22rem]`}
              data-testid="gal-folder"
            >
              {g.folders.map((f) => (
                <option key={f.path} value={f.path} disabled={!f.exists}>
                  {folderLabel(f)}
                </option>
              ))}
            </select>
          </label>
        )}
        <select value={g.usage} onChange={(e) => g.setFilter({ usage: e.target.value })} className={selectCls} data-testid="gal-usage">
          {["", "used", "unused"].map((u) => (
            <option key={u} value={u}>
              {gt(`usage_${u}`)}
              {u && g.counts[u] != null ? ` (${g.counts[u]})` : ""}
            </option>
          ))}
        </select>
        <select value={g.sort} onChange={(e) => g.setFilter({ sort: e.target.value })} className={selectCls} data-testid="gal-sort">
          {["new", "old", "large"].map((s) => (
            <option key={s} value={s}>
              {gt(`sort_${s}`)}
            </option>
          ))}
        </select>
        <div className="flex overflow-hidden rounded-lg border border-ink-600 text-xs">
          {["s", "m", "l"].map((s) => (
            <button
              key={s}
              onClick={() => g.setSize(s)}
              title={gt(`size${s.toUpperCase()}`)}
              className={`px-2 py-1.5 ${g.size === s ? "bg-ink-700 text-gray-100" : "text-gray-400 hover:bg-ink-750"}`}
            >
              {s.toUpperCase()}
            </button>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        {kinds.map((k) => (
          <button
            key={k || "all"}
            onClick={() => g.setFilter({ kind: k })}
            data-testid={`gal-kind-${k || "all"}`}
            className={`rounded-full border px-2.5 py-0.5 text-xs ${
              g.kind === k
                ? "border-emerald-600/60 bg-emerald-600/15 text-emerald-300"
                : "border-ink-600 text-gray-400 hover:bg-ink-750"
            }`}
          >
            {gt(`kind_${k}`)}
            <span className="ml-1 text-gray-500">{g.counts[k || "all"] ?? 0}</span>
          </button>
        ))}
        {(g.q || g.kind || g.usage) && (
          <span className="ml-1 text-xs text-gray-500" data-testid="gal-matched">
            {gt("matched", { n: g.total })}
          </span>
        )}
      </div>
    </div>
  );
}

const dayKey = (ts, lang) =>
  new Date(ts * 1000).toLocaleDateString(lang, { year: "numeric", month: "short", day: "numeric", weekday: "short" });

function GridView() {
  const gt = useGT();
  const lang = useLang();
  const g = useGallery();
  const sentinel = useRef(null);

  // 捲到底自動載入下一頁
  useEffect(() => {
    const el = sentinel.current;
    if (!el) return;
    const io = new IntersectionObserver((ents) => {
      if (ents.some((e) => e.isIntersecting)) useGallery.getState().loadMore();
    }, { rootMargin: "600px" });
    io.observe(el);
    return () => io.disconnect();
  }, [g.items.length, g.total]);

  // 依日期分段（依大小排序時不分段）
  const groups = useMemo(() => {
    if (g.sort === "large") return [{ key: "", items: g.items }];
    const out = [];
    for (const it of g.items) {
      const k = dayKey(it.mtime, lang);
      if (!out.length || out[out.length - 1].key !== k) out.push({ key: k, items: [] });
      out[out.length - 1].items.push(it);
    }
    return out;
  }, [g.items, g.sort, lang]);

  const selNames = Object.keys(g.selected);
  const nSel = selNames.length;
  const selBytes = selNames.reduce((n, k) => n + (g.selected[k]?.size || 0), 0);
  const selUsed = selNames.filter((k) => g.selected[k]?.used).length;
  const confirmDelete = useConfirmDelete();
  const [busy, setBusy] = useState(false);
  const [delErr, setDelErr] = useState("");
  const deleteSelected = async () => {
    const st = useGallery.getState();
    const names = Object.keys(st.selected);
    if (!names.length || busy) return;
    setBusy(true);
    setDelErr("");
    try {
      await confirmDelete(names, names.filter((k) => st.selected[k]?.used).length);
    } catch (e) {
      setDelErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  // 多選的鍵盤：Delete 刪除所選、Esc 清除 / 結束多選、Ctrl+A 全選已載入（看大圖或在輸入框打字時不攔）
  useEffect(() => {
    const onKey = (e) => {
      const st = useGallery.getState();
      if (st.detail || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target?.tagName)) return;
      const n = Object.keys(st.selected).length;
      if ((e.key === "Delete" || e.key === "Backspace") && n) deleteSelected();
      else if (e.key === "Escape" && (n || st.selecting)) n ? st.clearSelection() : st.setSelecting(false);
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a" && st.items.length) st.selectAllLoaded();
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <>
      <Toolbar />
      <main className="min-h-0 flex-1 overflow-y-auto px-2 py-2 sm:px-3" data-testid="gal-grid">
        {g.error && <ErrorBox text={g.error} />}
        {!g.loading && !g.items.length && !g.error && (
          <div className="flex flex-col items-center gap-2 py-16 text-sm text-gray-500">
            <ImageOff size={28} />
            {g.q || g.kind || g.usage ? gt("emptyFiltered") : gt("empty")}
          </div>
        )}
        {groups.map((grp) => (
          <section key={grp.key || "all"} className="mb-3">
            {grp.key && <DayHeader grp={grp} />}
            <div className={`grid gap-1.5 ${GRID[g.size] || GRID.m}`}>
              {grp.items.map((it) => (
                <Tile key={it.name} it={it} />
              ))}
            </div>
          </section>
        ))}
        <div ref={sentinel} className="h-1" />
        {g.items.length < g.total && (
          <div className="flex justify-center py-3">
            <button onClick={() => g.loadMore()} disabled={g.loading} className={btnCls} data-testid="gal-more">
              {g.loading && <Loader2 size={14} className="animate-spin" />}
              {gt("loadMore")} ({g.items.length}/{g.total})
            </button>
          </div>
        )}
        {g.loading && !g.items.length && (
          <div className="flex justify-center py-10 text-gray-500">
            <Loader2 size={20} className="animate-spin" />
          </div>
        )}
      </main>
      {g.selecting && (
        <div className="space-y-1.5 border-t border-ink-700 bg-ink-850 px-3 py-2" data-testid="gal-selbar">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-gray-200" data-testid="gal-selcount">
              {gt("selectedN", { n: nSel })}
              {nSel > 0 && <span className="ml-1 text-gray-500">· {formatBytes(selBytes)}</span>}
            </span>
            {selUsed > 0 && (
              <span className="flex items-center gap-1 text-xs text-amber-300" data-testid="gal-selused">
                <Link2 size={12} />
                {gt("selUsed", { n: selUsed })}
              </span>
            )}
            <div className="flex-1" />
            {g.items.some((i) => !g.selected[i.name]) && (
              <button onClick={() => g.selectAllLoaded()} className={btnCls} data-testid="gal-select-loaded">
                {gt("selectAll")}
              </button>
            )}
            {g.total > g.items.length && nSel < g.total && (
              <button onClick={() => g.selectAllMatching()} disabled={g.selectingAll} className={btnCls} data-testid="gal-select-matching">
                {g.selectingAll && <Loader2 size={14} className="animate-spin" />}
                {gt("selectMatching", { n: g.total })}
              </button>
            )}
            {nSel > 0 && (
              <button onClick={() => g.clearSelection()} className={btnCls} data-testid="gal-clear-selection">
                {gt("clearSelection")}
              </button>
            )}
            <button onClick={() => g.setSelecting(false)} className={btnCls}>
              {gt("cancel")}
            </button>
            <button
              disabled={!nSel || busy}
              onClick={deleteSelected}
              data-testid="gal-delete-selected"
              className="flex shrink-0 items-center gap-1.5 rounded-lg bg-red-600/80 px-3 py-1.5 text-sm text-white hover:bg-red-600 disabled:opacity-40"
            >
              {busy ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
              {nSel ? gt("deleteN", { n: nSel }) : gt("deleteSelected")}
            </button>
          </div>
          {delErr && <ErrorBox text={delErr} />}
          <p className="hidden text-[11px] text-gray-500 sm:block">{gt("selectHint")}</p>
        </div>
      )}
      {g.undo && <UndoToast />}
    </>
  );
}

// 日期標題：勾選框＝選 / 取消這一天載入的全部
function DayHeader({ grp }) {
  const gt = useGT();
  const selecting = useGallery((s) => s.selecting);
  const selected = useGallery((s) => s.selected);
  const selectGroup = useGallery((s) => s.selectGroup);
  const n = grp.items.filter((it) => selected[it.name]).length;
  const all = n === grp.items.length;
  return (
    <h2 className="group/day sticky top-0 z-10 -mx-2 flex items-center gap-1.5 bg-ink-900/90 px-2 py-1 text-xs font-medium text-gray-400 backdrop-blur sm:-mx-3 sm:px-3">
      <button
        onClick={() => selectGroup(grp.items, !all)}
        title={all ? gt("unselectDay") : gt("selectDay")}
        data-testid="gal-day-select"
        className={`rounded p-0.5 hover:text-emerald-300 ${
          selecting || n ? "" : "opacity-0 focus:opacity-100 group-hover/day:opacity-100"
        } ${all ? "text-emerald-400" : n ? "text-emerald-600" : "text-gray-500"}`}
      >
        {all ? <CheckSquare size={14} /> : <Square size={14} />}
      </button>
      {grp.key}
      <span className="text-gray-600">{n ? `${n} / ${grp.items.length}` : grp.items.length}</span>
    </h2>
  );
}

// 刪除後幾秒內可以復原（從垃圾桶放回這一批）
function UndoToast() {
  const gt = useGT();
  const undo = useGallery((s) => s.undo);
  const undoDelete = useGallery((s) => s.undoDelete);
  const dismissUndo = useGallery((s) => s.dismissUndo);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const id = setTimeout(() => {
      if (useGallery.getState().undo?.at === undo.at) dismissUndo();
    }, 12000);
    return () => clearTimeout(id);
  }, [undo.at, dismissUndo]);
  return (
    <div
      className="fixed bottom-24 left-1/2 z-40 flex max-w-[calc(100vw-2rem)] -translate-x-1/2 items-center gap-3 rounded-xl border border-ink-600 bg-ink-800 px-4 py-2 text-sm text-gray-200 shadow-lg"
      data-testid="gal-undo"
    >
      <span>{gt("movedToTrash", { n: undo.n })}</span>
      <button
        onClick={async () => {
          setBusy(true);
          try {
            await undoDelete();
          } finally {
            setBusy(false);
          }
        }}
        disabled={busy}
        data-testid="gal-undo-btn"
        className="flex items-center gap-1 font-medium text-emerald-300 hover:text-emerald-200"
      >
        {busy ? <Loader2 size={14} className="animate-spin" /> : <Undo2 size={14} />}
        {gt("undo")}
      </button>
      <button onClick={dismissUndo} className="text-gray-500 hover:text-gray-300">
        <X size={14} />
      </button>
    </div>
  );
}

function Tile({ it }) {
  const gt = useGT();
  const folder = useGallery((s) => s.folder);
  const size = useGallery((s) => s.size);
  const selecting = useGallery((s) => s.selecting);
  const selected = useGallery((s) => !!s.selected[it.name]);
  const toggle = useGallery((s) => s.toggle);
  const openDetail = useGallery((s) => s.openDetail);
  const [broken, setBroken] = useState(false);
  // 手機長按＝選這張（之後的點一下就是多選）
  const press = useRef({ timer: 0, x: 0, y: 0, fired: false });
  const startPress = (e) => {
    if (e.pointerType !== "touch") return;
    press.current = { x: e.clientX, y: e.clientY, fired: false,
      timer: setTimeout(() => { press.current.fired = true; toggle(it.name); }, 450) };
  };
  const endPress = () => clearTimeout(press.current.timer);
  const movePress = (e) => {
    if (Math.abs(e.clientX - press.current.x) + Math.abs(e.clientY - press.current.y) > 10) endPress();
  };
  const onClick = (e) => {
    if (press.current.fired) {
      press.current.fired = false;
      return;
    }
    if (selecting || e.shiftKey || e.ctrlKey || e.metaKey) toggle(it.name, e.shiftKey);
    else openDetail(it.name);
  };
  return (
    <div
      data-testid="gal-tile"
      data-name={it.name}
      data-selected={selected ? "1" : undefined}
      className={`group relative aspect-square select-none overflow-hidden rounded-lg border bg-ink-800 [-webkit-touch-callout:none] ${
        selected ? "border-emerald-500 ring-2 ring-emerald-500/60" : "border-ink-700 hover:border-ink-600"
      }`}
    >
      <button
        onClick={onClick}
        onPointerDown={startPress}
        onPointerUp={endPress}
        onPointerCancel={endPress}
        onPointerMove={movePress}
        onContextMenu={(e) => press.current.fired && e.preventDefault()}
        title={it.prompt || it.name}
        className="block h-full w-full"
      >
        {broken ? (
          <div className="flex h-full items-center justify-center text-gray-600">
            <ImageOff size={22} />
          </div>
        ) : (
          <img
            src={thumbUrl(folder, it, THUMB[size] || 384)}
            alt=""
            loading="lazy"
            decoding="async"
            draggable={false}
            onError={() => setBroken(true)}
            className={`h-full w-full object-cover object-top transition ${selected ? "scale-[0.94] rounded-md opacity-85" : "group-hover:scale-[1.02]"}`}
          />
        )}
      </button>
      {/* 種類 / 有用到 */}
      <div className="pointer-events-none absolute left-1 top-1 flex gap-1">
        {it.kind === "comic" && (
          <span className="flex items-center rounded bg-black/65 px-1 py-0.5 text-[10px] text-amber-200" title={gt("kind_comic")}>
            <BookOpen size={11} />
          </span>
        )}
        {it.kind === "upload" && (
          <span className="flex items-center rounded bg-black/65 px-1 py-0.5 text-[10px] text-sky-200" title={gt("kind_upload")}>
            <Upload size={11} />
          </span>
        )}
        {it.used > 0 && (
          <span
            className="flex items-center gap-0.5 rounded bg-black/65 px-1 py-0.5 text-[10px] text-emerald-200"
            title={gt("usedBadge", { n: it.used })}
            data-testid="gal-used"
          >
            <Link2 size={11} />
            {it.used}
          </span>
        )}
      </div>
      {/* 勾選框：滑過就出現，點了就進入多選 */}
      <button
        onClick={(e) => toggle(it.name, e.shiftKey)}
        title={gt("selectThis")}
        data-testid="gal-check"
        className={`absolute right-1 top-1 rounded bg-black/60 p-0.5 text-white transition hover:bg-black/80 ${
          selecting || selected ? "opacity-100" : "opacity-0 focus:opacity-100 group-hover:opacity-100"
        }`}
      >
        {selected ? <CheckSquare size={18} className="text-emerald-400" /> : <Square size={18} />}
      </button>
      {size !== "s" && (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 translate-y-full bg-gradient-to-t from-black/85 to-transparent px-1.5 pb-1 pt-4 text-left text-[10px] leading-snug text-gray-200 transition group-hover:translate-y-0">
          <div className="line-clamp-2">{it.prompt || <span className="text-gray-400">{gt("noMeta")}</span>}</div>
          <div className="mt-0.5 text-gray-400">
            {it.w}×{it.h} · {formatBytes(it.size)}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------- 垃圾桶 ----------------

function TrashView() {
  const gt = useGT();
  const lang = useLang();
  const trash = useGallery((s) => s.trash);
  const restore = useGallery((s) => s.restore);
  const purge = useGallery((s) => s.purge);
  const emptyTrash = useGallery((s) => s.emptyTrash);
  const error = useGallery((s) => s.error);
  const [sel, setSel] = useState({});
  const [msg, setMsg] = useState("");
  const ids = Object.keys(sel).filter((id) => trash.items.some((i) => i.id === id));

  const doRestore = async (list) => {
    setMsg("");
    try {
      const r = await restore(list);
      if (r.failed?.length) setMsg(gt("restoreFailed", { n: r.failed.length, msg: r.failed[0].error }));
      setSel({});
    } catch (e) {
      setMsg(e.message);
    }
  };
  const doPurge = async (list) => {
    if (!window.confirm(gt("confirmPurge", { n: list.length }))) return;
    try {
      await purge(list);
      setSel({});
    } catch (e) {
      setMsg(e.message);
    }
  };

  return (
    <main className="min-h-0 flex-1 overflow-y-auto p-3" data-testid="gal-trash">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="text-sm text-gray-300" data-testid="gal-trash-stats">
          {gt("trashStats", { n: trash.total, size: formatBytes(trash.total_bytes) })}
        </span>
        <div className="flex-1" />
        {ids.length > 0 && (
          <>
            <button onClick={() => doRestore(ids)} className={btnCls} data-testid="gal-restore-selected">
              <ArchiveRestore size={15} /> {gt("restoreSelected")} ({ids.length})
            </button>
            <button onClick={() => doPurge(ids)} className={`${btnCls} text-red-300`}>
              <Trash2 size={15} /> {gt("purgeSelected")} ({ids.length})
            </button>
          </>
        )}
        {trash.total > 0 && (
          <button
            onClick={async () => {
              if (!window.confirm(gt("confirmEmpty", { n: trash.total }))) return;
              await emptyTrash();
              setSel({});
            }}
            className="flex shrink-0 items-center gap-1.5 rounded-lg bg-red-600/80 px-3 py-1.5 text-sm text-white hover:bg-red-600"
            data-testid="gal-empty-trash"
          >
            <Trash2 size={14} /> {gt("emptyTrash")}
          </button>
        )}
      </div>
      <p className="mb-3 text-xs text-gray-500">{gt("trashHint")}</p>
      {(error || msg) && <ErrorBox text={msg || error} />}
      {!trash.items.length && (
        <div className="flex flex-col items-center gap-2 py-16 text-sm text-gray-500">
          <Trash2 size={28} />
          {gt("trashEmpty")}
        </div>
      )}
      <div className={`grid gap-2 ${GRID.m}`}>
        {trash.items.map((it) => (
          <div
            key={it.id}
            data-testid="gal-trash-item"
            data-name={it.name}
            className={`overflow-hidden rounded-lg border bg-ink-850 ${sel[it.id] ? "border-emerald-500" : "border-ink-700"}`}
          >
            <button
              onClick={() => setSel((s) => (s[it.id] ? Object.fromEntries(Object.entries(s).filter(([k]) => k !== it.id)) : { ...s, [it.id]: true }))}
              className="relative block aspect-square w-full bg-ink-800"
              title={it.prompt || it.name}
            >
              <img src={trashThumbUrl(it.id)} alt="" loading="lazy" className="h-full w-full object-cover object-top opacity-75" />
              <span className="absolute right-1 top-1 rounded bg-black/60 p-0.5 text-white">
                {sel[it.id] ? <CheckSquare size={16} className="text-emerald-400" /> : <Square size={16} />}
              </span>
            </button>
            <div className="space-y-1 p-1.5 text-[10px] leading-snug text-gray-400">
              <div className="truncate" title={it.from}>
                {gt("deletedAt", { t: new Date(it.deleted_at * 1000).toLocaleString(lang) })}
              </div>
              <div className="flex gap-1">
                <button
                  onClick={() => doRestore([it.id])}
                  data-testid="gal-restore"
                  className="flex flex-1 items-center justify-center gap-1 rounded border border-ink-600 py-1 text-gray-300 hover:bg-ink-750"
                >
                  <ArchiveRestore size={12} /> {gt("restore")}
                </button>
                <button
                  onClick={() => doPurge([it.id])}
                  title={gt("purge")}
                  data-testid="gal-purge"
                  className="rounded border border-ink-600 px-1.5 py-1 text-red-300 hover:bg-red-950/40"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </main>
  );
}

export function ErrorBox({ text }) {
  return (
    <div className="mb-2 flex items-start gap-2 rounded-lg border border-red-900/50 bg-red-950/40 px-3 py-2 text-sm text-red-300">
      <AlertCircle size={15} className="mt-0.5 shrink-0" />
      <span className="whitespace-pre-wrap break-words">{text}</span>
    </div>
  );
}
