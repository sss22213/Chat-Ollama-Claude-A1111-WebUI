import { useEffect, useState } from "react";
import { FolderOpen, FilePlus2, Loader2, Trash2, X } from "lucide-react";
import { useComic } from "../store/comic";
import { useCT } from "./comicI18n";

// 作品庫：列出伺服器上保存的漫畫作品（縮圖、標題、更新時間、格數），可開啟 / 刪除 / 新作品。
export default function ComicLibrary({ onClose }) {
  const ct = useCT();
  const projectId = useComic((s) => s.projectId);
  const listProjects = useComic((s) => s.listProjects);
  const openProject = useComic((s) => s.openProject);
  const deleteProject = useComic((s) => s.deleteProject);
  const newProject = useComic((s) => s.newProject);
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const reload = async () => {
    try {
      setItems(await listProjects());
      setError("");
    } catch (e) {
      setError(e.message || String(e));
      setItems([]);
    }
  };
  useEffect(() => {
    reload();
  }, []);

  const open = async (id) => {
    setBusy(id);
    try {
      await openProject(id);
      onClose();
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setBusy("");
    }
  };
  const remove = async (e, id) => {
    e.stopPropagation();
    if (!window.confirm(ct("deleteConfirm"))) return;
    setBusy(id);
    try {
      await deleteProject(id);
      await reload();
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setBusy("");
    }
  };

  const fmt = (ts) => (ts ? new Date(ts * 1000).toLocaleString() : "");

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 p-2 sm:p-4"
      onClick={onClose}
    >
      <div
        className="flex h-[80dvh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-ink-700 bg-ink-850"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-ink-700 px-4 py-3">
          <h2 className="flex min-w-0 flex-1 items-center gap-2 text-base font-semibold">
            <FolderOpen size={17} />
            <span className="truncate">{ct("library")}</span>
          </h2>
          <button
            onClick={() => {
              newProject();
              onClose();
            }}
            className="flex shrink-0 items-center gap-1.5 rounded-lg border border-ink-600 px-2.5 py-1.5 text-xs text-gray-200 hover:bg-ink-750"
          >
            <FilePlus2 size={14} /> {ct("newProject")}
          </button>
          <button
            onClick={onClose}
            className="shrink-0 rounded-lg p-1.5 text-gray-400 hover:bg-ink-750"
          >
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-3">
          {items === null && (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-gray-400">
              <Loader2 size={16} className="animate-spin" />
            </div>
          )}
          {error && <p className="mb-2 text-xs text-red-400">{error}</p>}
          {items && items.length === 0 && !error && (
            <p className="px-2 py-10 text-center text-sm leading-relaxed text-gray-500">
              {ct("libraryEmpty")}
            </p>
          )}
          {items && items.length > 0 && (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
              {items.map((it) => {
                const current = it.id === projectId;
                return (
                  <button
                    key={it.id}
                    onClick={() => open(it.id)}
                    disabled={busy === it.id}
                    className={`group relative flex flex-col overflow-hidden rounded-xl border text-left transition ${
                      current
                        ? "border-emerald-500/70 bg-ink-800"
                        : "border-ink-700 bg-ink-800 hover:border-ink-500"
                    }`}
                    title={it.title || ct("untitled")}
                  >
                    <div className="aspect-[3/4] w-full bg-ink-900">
                      {it.cover ? (
                        <img
                          src={it.cover}
                          alt=""
                          loading="lazy"
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <div className="flex h-full items-center justify-center text-xs text-gray-600">
                          {ct("panelsCount", { n: it.panel_count })}
                        </div>
                      )}
                    </div>
                    <div className="space-y-0.5 p-2">
                      <div className="truncate text-xs font-medium text-gray-200">
                        {it.title || ct("untitled")}
                        {current && (
                          <span className="ml-1 rounded bg-emerald-600/30 px-1 text-[10px] text-emerald-300">
                            {ct("currentProject")}
                          </span>
                        )}
                      </div>
                      <div className="truncate text-[10px] text-gray-500">
                        {ct("panelsCount", { n: it.panel_count })} · {fmt(it.updated_at)}
                      </div>
                    </div>
                    <span
                      role="button"
                      onClick={(e) => remove(e, it.id)}
                      title={ct("deleteProject")}
                      className="absolute right-1 top-1 rounded-md bg-black/50 p-1 text-gray-300 opacity-0 transition hover:bg-red-600 hover:text-white group-hover:opacity-100 focus:opacity-100"
                    >
                      {busy === it.id ? (
                        <Loader2 size={13} className="animate-spin" />
                      ) : (
                        <Trash2 size={13} />
                      )}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
