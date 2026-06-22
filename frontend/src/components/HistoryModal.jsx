import { useEffect, useRef, useState } from "react";
import {
  X,
  Search,
  History,
  Loader2,
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  ArrowLeft,
  SlidersHorizontal,
  Wand2,
  Copy,
  Check,
} from "lucide-react";
import { useChat } from "../store/chat";
import { useT } from "../i18n";
import { fetchPromptHistory, promptHistoryThumb } from "../lib/api";

const fmtDate = (sec) => {
  if (!sec) return "";
  try {
    return new Date(sec * 1000).toLocaleString();
  } catch {
    return "";
  }
};

export default function HistoryModal({ onClose }) {
  const t = useT();
  const applyHistory = useChat((s) => s.applyHistory);
  const generateFromHistory = useChat((s) => s.generateFromHistory);
  const streaming = useChat((s) => s.streaming);

  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null); // {items,total,page,pages}
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [selected, setSelected] = useState(null);

  // 搜尋去抖動：輸入停 300ms 才打 API，並回到第 1 頁
  useEffect(() => {
    const id = setTimeout(() => {
      setQ(qInput.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(id);
  }, [qInput]);

  // 依 page / q 抓資料
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setErr("");
    fetchPromptHistory(page, q)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setErr(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [page, q]);

  const items = data?.items || [];
  const pages = data?.pages || 1;

  const onApply = () => {
    applyHistory(selected);
    onClose();
  };
  const onGenerate = () => {
    generateFromHistory(selected);
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
            <History size={17} /> <span className="hidden sm:inline">{t("history")}</span>
          </h2>
          <div className="relative min-w-0 flex-1">
            <Search
              size={15}
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500"
            />
            <input
              value={qInput}
              onChange={(e) => setQInput(e.target.value)}
              placeholder={t("historySearch")}
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

        {/* 內容區：清單 或 詳情 */}
        {selected ? (
          <HistoryDetail
            record={selected}
            t={t}
            streaming={streaming}
            onBack={() => setSelected(null)}
            onApply={onApply}
            onGenerate={onGenerate}
          />
        ) : (
          <>
            <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-5">
              {loading && (
                <div className="flex items-center justify-center gap-2 py-10 text-sm text-gray-400">
                  <Loader2 size={16} className="animate-spin" /> {t("loading")}
                </div>
              )}
              {err && !loading && (
                <div className="flex items-start gap-2 rounded-lg border border-red-900/50 bg-red-950/40 px-3 py-2 text-sm text-red-300">
                  <AlertTriangle size={15} className="mt-0.5 shrink-0" />
                  <span>{err}</span>
                </div>
              )}
              {!loading && !err && items.length === 0 && (
                <div className="py-10 text-center text-sm text-gray-500">
                  {t("historyEmpty")}
                </div>
              )}
              {!loading && !err && items.length > 0 && (
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
                  {items.map((it) => (
                    <HistoryCard
                      key={it.id}
                      item={it}
                      onClick={() => setSelected(it)}
                    />
                  ))}
                </div>
              )}
            </div>

            {/* 分頁 */}
            {!err && (data?.total || 0) > 0 && (
              <div className="flex items-center justify-between border-t border-ink-700 px-4 py-2.5 text-sm sm:px-5">
                <span className="text-xs text-gray-500">
                  {t("historyTotal", { count: data.total })}
                </span>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page <= 1 || loading}
                    className="rounded-lg border border-ink-600 p-1.5 text-gray-300 hover:bg-ink-750 disabled:opacity-40"
                  >
                    <ChevronLeft size={16} />
                  </button>
                  <span className="tabular-nums text-xs text-gray-400">
                    {t("historyPageOf", { page, pages })}
                  </span>
                  <button
                    onClick={() => setPage((p) => Math.min(pages, p + 1))}
                    disabled={page >= pages || loading}
                    className="rounded-lg border border-ink-600 p-1.5 text-gray-300 hover:bg-ink-750 disabled:opacity-40"
                  >
                    <ChevronRight size={16} />
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function HistoryCard({ item, onClick }) {
  const [broken, setBroken] = useState(false);
  return (
    <button
      onClick={onClick}
      className="group flex flex-col overflow-hidden rounded-xl border border-ink-700 bg-ink-800 text-left transition hover:border-ink-500"
    >
      <div className="aspect-square w-full overflow-hidden bg-ink-900">
        {broken ? (
          <div className="flex h-full items-center justify-center text-gray-600">
            <History size={22} />
          </div>
        ) : (
          <img
            src={promptHistoryThumb(item.id, 256)}
            alt=""
            loading="lazy"
            onError={() => setBroken(true)}
            className="h-full w-full object-cover transition group-hover:scale-[1.03]"
          />
        )}
      </div>
      <div className="px-2 py-1.5">
        <p className="truncate text-xs text-gray-300" title={item.name}>
          {item.name || "—"}
        </p>
        <p className="mt-0.5 truncate text-[10px] text-gray-600">
          {fmtDate(item.created_at)}
        </p>
      </div>
    </button>
  );
}

function HistoryDetail({ record, t, streaming, onBack, onApply, onGenerate }) {
  const params = record.params || {};
  const orderedKeys = [
    "Steps",
    "Sampler",
    "CFG scale",
    "Seed",
    "Size",
    "Model",
  ].filter((k) => k in params);

  return (
    <>
      <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-5">
        <button
          onClick={onBack}
          className="mb-3 flex items-center gap-1.5 text-sm text-gray-400 hover:text-gray-200"
        >
          <ArrowLeft size={15} /> {record.name?.slice(0, 40) || "—"}
        </button>

        <div className="grid gap-4 md:grid-cols-[minmax(0,18rem)_1fr]">
          <img
            src={promptHistoryThumb(record.id, 512)}
            alt=""
            className="mx-auto max-h-72 w-full rounded-lg border border-ink-700 object-contain md:mx-0"
          />

          <div className="space-y-3">
            {record.prompt && (
              <FieldCopy label="Prompt" value={record.prompt} t={t} />
            )}
            {record.negative_prompt && (
              <FieldCopy
                label="Negative prompt"
                value={record.negative_prompt}
                t={t}
              />
            )}
            {orderedKeys.length > 0 && (
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 rounded-lg bg-ink-900 p-2.5 text-xs">
                {orderedKeys.map((k) => (
                  <div key={k} className="flex gap-1.5">
                    <span className="shrink-0 font-medium text-gray-500">
                      {k}:
                    </span>
                    <span className="break-all text-gray-200">{params[k]}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 動作列 */}
      <div className="flex items-center justify-end gap-2 border-t border-ink-700 px-4 py-3 sm:px-5">
        <button
          onClick={onApply}
          className="flex items-center gap-1.5 rounded-lg border border-ink-600 px-4 py-2 text-sm font-medium text-gray-200 hover:bg-ink-750"
        >
          <SlidersHorizontal size={15} /> {t("historyApply")}
        </button>
        <button
          onClick={onGenerate}
          disabled={streaming || !record.prompt}
          className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-ink-600 disabled:text-gray-500"
        >
          <Wand2 size={15} /> {t("historyGenerate")}
        </button>
      </div>
    </>
  );
}

function FieldCopy({ label, value, t }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* 忽略 */
    }
  };
  return (
    <div className="rounded-lg bg-ink-900 p-2.5">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-xs font-medium text-gray-500">{label}</span>
        <button
          onClick={copy}
          className="flex items-center gap-1 text-xs text-gray-400 hover:text-emerald-300"
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {copied ? t("copied") : t("copy")}
        </button>
      </div>
      <p className="max-h-40 overflow-auto whitespace-pre-wrap break-words text-xs leading-relaxed text-gray-200">
        {value}
      </p>
    </div>
  );
}
