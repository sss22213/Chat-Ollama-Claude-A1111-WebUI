import { useEffect, useState } from "react";
import { X, Search, Layers, Loader2, Plus, Wand2, RefreshCw } from "lucide-react";
import { useT } from "../i18n";
import { fetchLoras, refreshLoras, loraThumb } from "../lib/api";

/** LoRA 縮圖：載入失敗（後端 404 = 無預覽圖）就改顯示首字母佔位塊。 */
function LoraThumb({ name, alias }) {
  const [failed, setFailed] = useState(false);
  const letter = (alias || name || "?").trim().charAt(0).toUpperCase() || "?";
  if (failed) {
    return (
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-ink-700 text-sm font-semibold text-gray-300">
        {letter}
      </div>
    );
  }
  return (
    <img
      src={loraThumb(name, 96)}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
      className="h-10 w-10 shrink-0 rounded-md bg-ink-700 object-cover"
    />
  );
}

/**
 * LoRA 搜尋器（清單 + 觸發詞），與 CharacterPicker 同一套互動。
 * onInsert(c)：把 c.prompt（<lora:name:1> + 觸發詞）帶入輸入框；
 * onGenerate(c)：直接生成一張。
 */
export default function LoraPicker({ onClose, onInsert, onGenerate, streaming }) {
  const t = useT();
  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    const id = setTimeout(() => setQ(qInput.trim()), 250);
    return () => clearTimeout(id);
  }, [qInput]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fetchLoras(q) // 不帶 limit → 顯示全部 LoRA
      .then((d) => alive && setItems(d))
      .catch(() => alive && setItems([]))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [q]);

  // 請 A1111 重掃 LoRA 目錄後重新載入（放了新檔不必重啟 WebUI）
  const doRefresh = async () => {
    setRefreshing(true);
    try {
      await refreshLoras();
      const d = await fetchLoras(q); // 不帶 limit → 顯示全部 LoRA
      setItems(d);
    } catch {
      /* 連不到 A1111 等 → 維持現狀 */
    } finally {
      setRefreshing(false);
    }
  };

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
            <Layers size={17} />
            <span className="hidden sm:inline">{t("loras")}</span>
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
              placeholder={t("loraSearchPh")}
              className="w-full rounded-lg border border-ink-600 bg-ink-800 py-1.5 pl-8 pr-3 text-sm outline-none focus:border-ink-500"
            />
          </div>
          <button
            onClick={doRefresh}
            disabled={refreshing}
            title={t("loraRefresh")}
            className="shrink-0 rounded-lg p-1.5 text-gray-400 hover:bg-ink-750 disabled:opacity-50"
          >
            <RefreshCw size={16} className={refreshing ? "animate-spin" : ""} />
          </button>
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
              {t("loraEmpty")}
            </div>
          )}
          {!loading &&
            items.map((c, i) => (
              <div
                key={`${c.name}-${i}`}
                className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-ink-800"
              >
                <LoraThumb name={c.name} alias={c.alias} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm text-gray-200">{c.alias}</div>
                  <div
                    className="truncate font-mono text-[11px] text-gray-600"
                    title={c.prompt}
                  >
                    {c.triggers && c.triggers.length
                      ? c.triggers.join(", ")
                      : `<lora:${c.name}:1>`}
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
