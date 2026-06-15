import { useEffect, useState } from "react";
import {
  X,
  Folder,
  CornerLeftUp,
  FolderPlus,
  Check,
  Loader2,
  AlertTriangle,
} from "lucide-react";
import { browseDir, makeDir } from "../lib/api";
import { useT } from "../i18n";

/**
 * 伺服器端資料夾選擇器：可逐層點選、直接輸入路徑、或新增資料夾。
 * onPick(path) 在按「選擇此資料夾」時呼叫。
 * requireWritable=false 時可選唯讀資料夾（如歷史目錄常是唯讀掛載）。
 * title 可覆寫標題（不同用途）。
 */
export default function DirectoryPicker({
  initialPath,
  onPick,
  onClose,
  requireWritable = true,
  title,
}) {
  const t = useT();
  const canPick = (c) => !!c && (!requireWritable || c.writable);
  const [cur, setCur] = useState(null); // {path, parent, dirs, writable}
  const [pathInput, setPathInput] = useState(initialPath || "");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");

  const go = async (path) => {
    setLoading(true);
    setError("");
    try {
      const data = await browseDir(path);
      setCur(data);
      setPathInput(data.path);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    go(initialPath || undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onCreate = async () => {
    const name = newName.trim();
    if (!name || !cur) return;
    try {
      const { path } = await makeDir(cur.path, name);
      setCreating(false);
      setNewName("");
      await go(path); // 進入新建的資料夾
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-2 sm:p-4"
      onClick={onClose}
    >
      <div
        className="flex h-[34rem] max-h-[92vh] w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-ink-700 bg-ink-850"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-ink-700 px-5 py-3">
          <h2 className="text-base font-semibold">{title || t("pickerTitle")}</h2>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-gray-400 hover:bg-ink-750"
          >
            <X size={18} />
          </button>
        </div>

        {/* 路徑輸入列 */}
        <div className="flex items-center gap-2 border-b border-ink-700 px-4 py-2.5">
          <input
            value={pathInput}
            onChange={(e) => setPathInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && go(pathInput.trim())}
            placeholder={t("pathPh")}
            spellCheck={false}
            className="flex-1 rounded-lg border border-ink-600 bg-ink-800 px-3 py-1.5 font-mono text-xs outline-none focus:border-ink-500"
          />
          <button
            onClick={() => go(pathInput.trim())}
            className="rounded-lg border border-ink-600 px-3 py-1.5 text-sm hover:bg-ink-750"
          >
            {t("go")}
          </button>
        </div>

        {/* 資料夾清單 */}
        <div className="relative flex-1 overflow-y-auto px-2 py-2">
          {loading && (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-gray-400">
              <Loader2 size={16} className="animate-spin" /> {t("loading")}
            </div>
          )}

          {!loading && cur && (
            <>
              {cur.parent && (
                <Row icon={CornerLeftUp} label={t("upDir")} onClick={() => go(cur.parent)} muted />
              )}
              {cur.dirs.length === 0 && (
                <div className="px-3 py-6 text-center text-xs text-gray-500">
                  {t("noSubfolders")}
                </div>
              )}
              {cur.dirs.map((d) => (
                <Row
                  key={d}
                  icon={Folder}
                  label={d}
                  onClick={() => go(joinPath(cur.path, d))}
                />
              ))}
            </>
          )}
        </div>

        {error && (
          <div className="flex items-center gap-2 border-t border-ink-700 bg-red-950/30 px-4 py-2 text-xs text-red-300">
            <AlertTriangle size={14} /> {error}
          </div>
        )}

        {/* 新增資料夾列 */}
        {creating && (
          <div className="flex items-center gap-2 border-t border-ink-700 px-4 py-2.5">
            <input
              autoFocus
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && onCreate()}
              placeholder={t("newFolderPh")}
              className="flex-1 rounded-lg border border-ink-600 bg-ink-800 px-3 py-1.5 text-sm outline-none focus:border-ink-500"
            />
            <button
              onClick={onCreate}
              className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm text-white hover:bg-emerald-500"
            >
              {t("create")}
            </button>
            <button
              onClick={() => setCreating(false)}
              className="rounded-lg border border-ink-600 px-3 py-1.5 text-sm hover:bg-ink-750"
            >
              {t("cancel")}
            </button>
          </div>
        )}

        {/* 底部操作 */}
        <div className="flex items-center gap-2 border-t border-ink-700 px-4 py-3">
          <button
            onClick={() => setCreating(true)}
            disabled={!cur?.writable}
            title={cur?.writable ? t("newFolder") : t("folderNotWritable")}
            className="flex items-center gap-1.5 rounded-lg border border-ink-600 px-3 py-1.5 text-sm text-gray-300 hover:bg-ink-750 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <FolderPlus size={15} /> {t("newFolder")}
          </button>
          <div className="flex-1 truncate px-1 text-xs text-gray-500">
            {cur?.path}
          </div>
          <button
            onClick={() => onClose()}
            className="rounded-lg border border-ink-600 px-3 py-1.5 text-sm hover:bg-ink-750"
          >
            {t("cancel")}
          </button>
          <button
            onClick={() => canPick(cur) && onPick(cur.path)}
            disabled={!canPick(cur)}
            title={canPick(cur) ? "" : t("folderNotWritable")}
            className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-ink-600 disabled:text-gray-500"
          >
            <Check size={15} /> {t("chooseThis")}
          </button>
        </div>
      </div>
    </div>
  );
}

function Row({ icon: Icon, label, onClick, muted }) {
  return (
    <button
      onClick={onClick}
      className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm hover:bg-ink-750 ${
        muted ? "text-gray-400" : "text-gray-200"
      }`}
    >
      <Icon size={16} className="shrink-0 text-amber-400/80" />
      <span className="truncate">{label}</span>
    </button>
  );
}

function joinPath(base, name) {
  return base.endsWith("/") ? base + name : base + "/" + name;
}
