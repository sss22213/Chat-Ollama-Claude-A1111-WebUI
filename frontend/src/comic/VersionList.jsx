import { useEffect, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Eye,
  History,
  RotateCcw,
  Save,
  Trash2,
  X,
} from "lucide-react";
import { useComic } from "../store/comic";
import { useCT } from "./comicI18n";

// 分鏡版本歷史：AI 生成分鏡 / 匯入腳本 / 回復之前自動留的版本，可預覽、回復、刪除、手動存一版。
// 清單來自伺服器（不設上限）；本機 store 只快取最近幾版，預覽 / 回復更早的版本時再向伺服器取。
const LABEL_KEY = {
  auto: "versionAuto",
  import: "versionImport",
  beforeRestore: "versionBeforeRestore",
  manual: "versionManual",
};

export default function VersionList() {
  const ct = useCT();
  const cache = useComic((s) => s.versions);
  const projectId = useComic((s) => s.projectId);
  const hasPanels = useComic((s) => s.panels.length > 0);
  const snapshotPanels = useComic((s) => s.snapshotPanels);
  const listVersions = useComic((s) => s.listVersions);
  const getVersion = useComic((s) => s.getVersion);
  const restoreVersion = useComic((s) => s.restoreVersion);
  const deleteVersion = useComic((s) => s.deleteVersion);
  const [open, setOpen] = useState(false);
  const [remote, setRemote] = useState(null); // 伺服器上的完整清單（摘要）
  const [preview, setPreview] = useState(null); // 整份版本（含分鏡格）
  const [error, setError] = useState("");
  const fmt = (ms) => new Date(ms).toLocaleString();
  const label = (v) => ct(LABEL_KEY[v.label] || "versionManual");
  // 清單：伺服器有就用伺服器的，還沒載到就先顯示本機快取
  const versions = remote ?? cache.map(({ panels, pending, ...rest }) => rest);
  const cacheKey = cache.map((v) => v.id + (v.pending ? "!" : "")).join(",");

  useEffect(() => {
    let alive = true;
    listVersions().then((list) => alive && setRemote(list));
    return () => {
      alive = false;
    };
  }, [listVersions, projectId, cacheKey]);

  const showPreview = async (id) => {
    setError("");
    try {
      setPreview(await getVersion(id));
    } catch (e) {
      setError(e.message || String(e));
    }
  };
  const restore = async (id) => {
    setError("");
    try {
      await restoreVersion(id);
      setPreview(null);
    } catch (e) {
      setError(e.message || String(e));
    }
  };
  const remove = async (id) => {
    if (!window.confirm(ct("deleteVersionConfirm"))) return;
    await deleteVersion(id);
    setRemote((list) => (list ? list.filter((v) => v.id !== id) : list));
    if (preview?.id === id) setPreview(null);
  };

  return (
    <section data-testid="versions">
      <div className="flex items-center gap-1">
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex min-w-0 flex-1 items-center gap-1 text-left text-sm font-semibold text-gray-200"
        >
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <History size={14} />
          <span className="truncate">{ct("versions")}</span>
          <span className="text-xs font-normal text-gray-500">({versions.length})</span>
        </button>
        <button
          onClick={() => {
            snapshotPanels("manual");
            setOpen(true);
          }}
          disabled={!hasPanels}
          title={ct("saveVersion")}
          className="flex shrink-0 items-center gap-1 rounded-md border border-ink-600 px-2 py-1 text-[11px] text-gray-300 hover:bg-ink-750 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Save size={12} /> {ct("saveVersion")}
        </button>
      </div>
      <p className="mt-1 text-[11px] leading-snug text-gray-500">{ct("versionsHint")}</p>

      {error && <p className="mt-1 text-[11px] text-red-400">{error}</p>}
      {open && (
        <div className="mt-2 space-y-1.5">
          {versions.length === 0 && (
            <p className="rounded-md border border-dashed border-ink-700 px-2 py-3 text-center text-[11px] text-gray-500">
              {ct("noVersions")}
            </p>
          )}
          {versions.map((v) => (
            <div
              key={v.id}
              className="flex gap-2 rounded-lg border border-ink-700 bg-ink-800 p-1.5"
            >
              <button
                onClick={() => showPreview(v.id)}
                title={ct("previewVersion")}
                className="h-14 w-11 shrink-0 overflow-hidden rounded-md bg-ink-900"
              >
                {v.cover ? (
                  <img src={v.cover} alt="" className="h-full w-full object-cover" />
                ) : (
                  <span className="flex h-full items-center justify-center text-[10px] text-gray-600">
                    {v.count}
                  </span>
                )}
              </button>
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs text-gray-200">
                  {label(v)}
                  <span className="ml-1 text-[10px] text-gray-500">{fmt(v.at)}</span>
                </div>
                <div className="text-[10px] text-gray-500">
                  {ct("versionMeta", { n: v.count, m: v.images })}
                </div>
                {v.premise && (
                  <div className="truncate text-[10px] text-gray-600" title={v.premise}>
                    {v.premise}
                  </div>
                )}
                <div className="mt-1 flex gap-1">
                  <button
                    onClick={() => showPreview(v.id)}
                    className="flex items-center gap-1 rounded border border-ink-600 px-1.5 py-0.5 text-[10px] text-gray-300 hover:bg-ink-750"
                  >
                    <Eye size={11} /> {ct("previewVersion")}
                  </button>
                  <button
                    onClick={() => restore(v.id)}
                    className="flex items-center gap-1 rounded border border-emerald-700/60 px-1.5 py-0.5 text-[10px] text-emerald-300 hover:bg-emerald-900/30"
                  >
                    <RotateCcw size={11} /> {ct("restoreVersion")}
                  </button>
                  <button
                    onClick={() => remove(v.id)}
                    title={ct("deleteVersion")}
                    className="ml-auto rounded p-0.5 text-gray-500 hover:text-red-400"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {preview && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 p-2 sm:p-4"
          onClick={() => setPreview(null)}
        >
          <div
            data-testid="version-preview"
            className="flex h-[85dvh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-ink-700 bg-ink-850"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-2 border-b border-ink-700 px-4 py-3">
              <h2 className="flex min-w-0 flex-1 items-center gap-2 text-base font-semibold">
                <History size={17} />
                <span className="truncate">
                  {label(preview)} · {fmt(preview.at)}
                </span>
              </h2>
              <button
                onClick={() => restore(preview.id)}
                className="flex shrink-0 items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500"
              >
                <RotateCcw size={14} /> {ct("restoreVersion")}
              </button>
              <button
                onClick={() => setPreview(null)}
                className="shrink-0 rounded-lg p-1.5 text-gray-400 hover:bg-ink-750"
              >
                <X size={18} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-3">
              {preview.premise && (
                <p className="mb-3 whitespace-pre-wrap text-xs leading-relaxed text-gray-400">
                  {preview.premise}
                </p>
              )}
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
                {preview.panels.map((p, i) => (
                  <div
                    key={p.id || i}
                    className="overflow-hidden rounded-lg border border-ink-700 bg-ink-800"
                  >
                    <div className="aspect-[7/9] w-full bg-ink-900">
                      {p.image?.url ? (
                        <img
                          src={p.image.url}
                          alt=""
                          loading="lazy"
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <div className="flex h-full items-center justify-center text-[10px] text-gray-600">
                          {ct("panel", { n: i + 1 })}
                        </div>
                      )}
                    </div>
                    <div className="space-y-1 p-2 text-[11px]">
                      <div className="font-medium text-gray-300">{ct("panel", { n: i + 1 })}</div>
                      {p.expression && (
                        <div className="text-amber-300/90">{p.expression}</div>
                      )}
                      <div className="line-clamp-3 text-gray-400" title={p.prompt}>
                        {p.prompt}
                      </div>
                      {(p.bubbles || []).map((b) => (
                        <div key={b.id} className="truncate text-gray-500">
                          {b.type === "caption" ? "▭ " : "💬 "}
                          {b.speaker ? `${b.speaker}：` : ""}
                          {b.text}
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
