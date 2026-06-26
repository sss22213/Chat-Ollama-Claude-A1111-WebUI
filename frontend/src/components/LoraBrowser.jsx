import { useEffect, useState } from "react";
import {
  X,
  Search,
  Layers,
  Loader2,
  ArrowLeft,
  Plus,
  Wand2,
  RefreshCw,
  Copy,
  Check,
} from "lucide-react";
import { useChat } from "../store/chat";
import { useT } from "../i18n";
import { fetchLoras, refreshLoras, loraThumb } from "../lib/api";

/**
 * 大型 LoRA 瀏覽器（縮圖牆 + 詳情），與「提示詞歷史」同一套互動，放在 TopBar 歷史按鈕旁。
 * 點卡片看詳情（大預覽圖 + 觸發詞），可「帶入」輸入框或「直接生成」。
 * 直接接 store：insertComposer（附加到輸入框）、generateLora（直接生圖）。
 */
// onInsert / onGenerate 可覆寫動作（漫畫工作室帶入畫風）；不傳則沿用聊天 store 行為。
// onGenerate={null} 可隱藏「直接生成」。
export default function LoraBrowser({ onClose, onInsert, onGenerate }) {
  const t = useT();
  const streaming = useChat((s) => s.streaming);
  const insertComposer = useChat((s) => s.insertComposer);
  const generateLora = useChat((s) => s.generateLora);
  const showGenerate = onGenerate !== null;

  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selected, setSelected] = useState(null);

  // 搜尋去抖動
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

  // 請 A1111 重掃 LoRA 目錄後重新載入
  const doRefresh = async () => {
    setRefreshing(true);
    try {
      await refreshLoras();
      setItems(await fetchLoras(q));
    } catch {
      /* 連不到 A1111 → 維持現狀 */
    } finally {
      setRefreshing(false);
    }
  };

  const doInsert = (c) => {
    if (onInsert) onInsert(c);
    else insertComposer(c.prompt || `<lora:${c.name}:1>`);
    onClose();
  };
  const doGenerate = (c) => {
    if (onGenerate) onGenerate(c);
    else generateLora(c);
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 p-2 sm:p-4"
      onClick={onClose}
    >
      <div
        className="flex h-[92dvh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-ink-700 bg-ink-850 sm:h-[88dvh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 標題列 + 搜尋 */}
        <div className="flex items-center gap-2 border-b border-ink-700 px-4 py-3 sm:gap-3 sm:px-5">
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

        {/* 內容區：縮圖牆 或 詳情 */}
        {selected ? (
          <LoraDetail
            lora={selected}
            t={t}
            streaming={streaming}
            onBack={() => setSelected(null)}
            onInsert={() => doInsert(selected)}
            onGenerate={() => doGenerate(selected)}
            showGenerate={showGenerate}
          />
        ) : (
          <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-5">
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
            {!loading && items.length > 0 && (
              <>
                <p className="mb-3 text-xs text-gray-500">
                  {t("historyTotal", { count: items.length })}
                </p>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
                  {items.map((c, i) => (
                    <LoraCard
                      key={`${c.name}-${i}`}
                      lora={c}
                      onClick={() => setSelected(c)}
                    />
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/** 縮圖牆卡片：縮圖載入失敗（後端 404 = 無預覽圖）顯示首字母佔位塊。 */
function LoraCard({ lora, onClick }) {
  const [broken, setBroken] = useState(false);
  const letter = (lora.alias || lora.name || "?").trim().charAt(0).toUpperCase();
  return (
    <button
      onClick={onClick}
      className="group flex flex-col overflow-hidden rounded-xl border border-ink-700 bg-ink-800 text-left transition hover:border-ink-500"
    >
      <div className="aspect-square w-full overflow-hidden bg-ink-900">
        {broken ? (
          <div className="flex h-full flex-col items-center justify-center gap-1 text-gray-600">
            <Layers size={20} />
            <span className="text-lg font-semibold text-gray-500">{letter}</span>
          </div>
        ) : (
          <img
            src={loraThumb(lora.name, 256)}
            alt=""
            loading="lazy"
            onError={() => setBroken(true)}
            className="h-full w-full object-cover transition group-hover:scale-[1.03]"
          />
        )}
      </div>
      <div className="px-2 py-1.5">
        <p className="truncate text-xs text-gray-300" title={lora.alias}>
          {lora.alias}
        </p>
        <p className="mt-0.5 truncate text-[10px] text-gray-600">
          {lora.triggers && lora.triggers.length
            ? lora.triggers.slice(0, 3).join(", ")
            : `<lora:${lora.name}:1>`}
        </p>
      </div>
    </button>
  );
}

function LoraDetail({
  lora,
  t,
  streaming,
  onBack,
  onInsert,
  onGenerate,
  showGenerate = true,
}) {
  const [broken, setBroken] = useState(false);
  const [copied, setCopied] = useState(false);
  const letter = (lora.alias || lora.name || "?").trim().charAt(0).toUpperCase();

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(lora.prompt || `<lora:${lora.name}:1>`);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* 忽略 */
    }
  };

  return (
    <>
      <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-5">
        <button
          onClick={onBack}
          className="mb-3 flex items-center gap-1.5 text-sm text-gray-400 hover:text-gray-200"
        >
          <ArrowLeft size={15} /> {lora.alias}
        </button>

        <div className="grid gap-4 md:grid-cols-[minmax(0,18rem)_1fr]">
          <div className="mx-auto aspect-square w-full max-w-72 overflow-hidden rounded-lg border border-ink-700 bg-ink-900 md:mx-0">
            {broken ? (
              <div className="flex h-full flex-col items-center justify-center gap-2 text-gray-600">
                <Layers size={28} />
                <span className="text-2xl font-semibold text-gray-500">
                  {letter}
                </span>
              </div>
            ) : (
              <img
                src={loraThumb(lora.name, 512)}
                alt=""
                onError={() => setBroken(true)}
                className="h-full w-full object-cover"
              />
            )}
          </div>

          <div className="space-y-3">
            {/* 帶入用的字串（<lora:name:1> + 觸發詞） */}
            <div className="rounded-lg bg-ink-900 p-2.5">
              <div className="mb-1 flex items-center justify-between">
                <span className="text-xs font-medium text-gray-500">Prompt</span>
                <button
                  onClick={copy}
                  className="flex items-center gap-1 text-xs text-gray-400 hover:text-emerald-300"
                >
                  {copied ? <Check size={12} /> : <Copy size={12} />}
                  {copied ? t("copied") : t("copy")}
                </button>
              </div>
              <p className="max-h-40 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-gray-200">
                {lora.prompt || `<lora:${lora.name}:1>`}
              </p>
            </div>

            {/* 觸發詞清單 */}
            {lora.triggers && lora.triggers.length > 0 && (
              <div className="rounded-lg bg-ink-900 p-2.5">
                <span className="text-xs font-medium text-gray-500">
                  {t("loraTriggers")}
                </span>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {lora.triggers.map((trig, i) => (
                    <span
                      key={`${trig}-${i}`}
                      className="rounded-md bg-ink-800 px-2 py-0.5 text-xs text-gray-300"
                    >
                      {trig}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 動作列 */}
      <div className="flex items-center justify-end gap-2 border-t border-ink-700 px-4 py-3 sm:px-5">
        <button
          onClick={onInsert}
          className="flex items-center gap-1.5 rounded-lg border border-ink-600 px-4 py-2 text-sm font-medium text-gray-200 hover:bg-ink-750"
        >
          <Plus size={15} /> {t("charInsert")}
        </button>
        {showGenerate && (
          <button
            onClick={onGenerate}
            disabled={streaming}
            className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-ink-600 disabled:text-gray-500"
          >
            <Wand2 size={15} /> {t("historyGenerate")}
          </button>
        )}
      </div>
    </>
  );
}
