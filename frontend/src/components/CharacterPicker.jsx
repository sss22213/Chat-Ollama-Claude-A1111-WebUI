import { useEffect, useState } from "react";
import { X, Search, Users, Loader2, Plus, Wand2 } from "lucide-react";
import { useT } from "../i18n";
import { fetchCharacters } from "../lib/api";

/**
 * WAI / Illustrious 角色關鍵字搜尋器。
 * onInsert(tag)：把角色 tag 帶入輸入框；onGenerate(tag)：直接生成一張。
 */
export default function CharacterPicker({ onClose, onInsert, onGenerate, streaming }) {
  const t = useT();
  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const id = setTimeout(() => setQ(qInput.trim()), 250);
    return () => clearTimeout(id);
  }, [qInput]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fetchCharacters(q, 80)
      .then((d) => alive && setItems(d))
      .catch(() => alive && setItems([]))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [q]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 p-2 sm:p-4"
      onClick={onClose}
    >
      <div
        className="flex h-[80dvh] w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-ink-700 bg-ink-850"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-ink-700 px-4 py-3">
          <h2 className="flex shrink-0 items-center gap-2 text-base font-semibold">
            <Users size={17} />
            <span className="hidden sm:inline">{t("characters")}</span>
          </h2>
          <div className="relative min-w-0 flex-1">
            <Search
              size={15}
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500"
            />
            <input
              autoFocus
              value={qInput}
              onChange={(e) => setQInput(e.target.value)}
              placeholder={t("charSearchPh")}
              className="w-full rounded-lg border border-ink-600 bg-ink-800 py-1.5 pl-8 pr-3 text-sm outline-none focus:border-ink-500"
            />
          </div>
          <button
            onClick={onClose}
            className="shrink-0 rounded-lg p-1.5 text-gray-400 hover:bg-ink-750"
          >
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-2 py-2">
          {loading && (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-gray-400">
              <Loader2 size={16} className="animate-spin" /> {t("loading")}
            </div>
          )}
          {!loading && items.length === 0 && (
            <div className="py-10 text-center text-sm text-gray-500">
              {t("charEmpty")}
            </div>
          )}
          {!loading &&
            items.map((c, i) => (
              <div
                key={`${c.tag}-${i}`}
                className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-ink-800"
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm text-gray-200">
                    {c.name}
                    {c.series ? (
                      <span className="text-gray-500"> · {c.series}</span>
                    ) : null}
                  </div>
                  <div
                    className="truncate font-mono text-[11px] text-gray-600"
                    title={c.prompt || c.tag}
                  >
                    {c.prompt ? `📝 ${c.prompt}` : c.tag}
                  </div>
                </div>
                <button
                  onClick={() => onInsert(c)}
                  title={t("charInsert")}
                  className="flex shrink-0 items-center gap-1 rounded-lg border border-ink-600 px-2 py-1 text-xs text-gray-200 hover:bg-ink-750"
                >
                  <Plus size={13} /> {t("charInsert")}
                </button>
                <button
                  onClick={() => onGenerate(c)}
                  disabled={streaming}
                  title={t("historyGenerate")}
                  className="flex shrink-0 items-center gap-1 rounded-lg bg-emerald-600 px-2 py-1 text-xs text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-ink-600 disabled:text-gray-500"
                >
                  <Wand2 size={13} />
                </button>
              </div>
            ))}
        </div>
      </div>
    </div>
  );
}
