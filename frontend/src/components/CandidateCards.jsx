import { useState } from "react";
import { Download, ExternalLink, Copy, Check, EyeOff } from "lucide-react";
import { useChat } from "../store/chat";
import { useT } from "../i18n";

/**
 * 技能工具回傳的候選清單卡片（目前：civitai 搜尋結果 kind="civitai_models"）。
 * 每張卡片：範例圖縮圖（後端暫存，點了開原圖）、名稱、類型 / 基底模型、下載數、觸發詞、
 * 「下載這個」按鈕 → 送一則對話訊息請 Civitai Helper 下載（需啟用該技能）。
 */
export default function CandidateCards({ group }) {
  const t = useT();
  const sendMessage = useChat((s) => s.sendMessage);
  const streaming = useChat((s) => s.streaming);
  const [copied, setCopied] = useState(null);
  const [showNsfw, setShowNsfw] = useState(true); // 預設直接顯示 NSFW（不模糊），按鈕可切換隱藏
  const items = group?.items || [];
  if (!items.length) return null;

  const download = (c) => {
    if (streaming) return;
    sendMessage(t("candidateDownloadMsg", { name: c.name, url: c.url }));
  };
  const copyWords = async (c) => {
    const text = [c.file ? `<lora:${c.file.replace(/\.[^.]+$/, "")}:0.8>` : "", ...(c.trained_words || [])]
      .filter(Boolean)
      .join(", ");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(c.id);
      setTimeout(() => setCopied(null), 1500);
    } catch {
      /* 剪貼簿不可用 */
    }
  };
  const fmt = (n) => (n == null ? "" : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));

  return (
    <div data-testid="candidates" className="rounded-xl border border-ink-700 bg-ink-850 p-3">
      <div className="mb-2 flex items-center gap-2 text-xs text-gray-400">
        <span>{t("candidatesTitle", { count: items.length })}</span>
        <div className="flex-1" />
        {items.some((c) => c.nsfw || (c.images || []).some((im) => im.nsfw)) && (
          <button
            onClick={() => setShowNsfw((v) => !v)}
            className="flex items-center gap-1 rounded border border-ink-600 px-1.5 py-0.5 hover:bg-ink-750"
          >
            <EyeOff size={12} /> {showNsfw ? t("candidateHideNsfw") : t("candidateShowNsfw")}
          </button>
        )}
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((c, idx) => (
          <div
            key={c.version_id || c.id || idx}
            data-testid="candidate"
            className="flex flex-col overflow-hidden rounded-lg border border-ink-700 bg-ink-800"
          >
            <div className="flex h-40 gap-0.5 overflow-hidden bg-ink-900">
              {(c.images || []).length === 0 && (
                <div className="flex flex-1 items-center justify-center text-xs text-gray-600">
                  {t("candidateNoImage")}
                </div>
              )}
              {(c.images || []).map((im, j) => {
                const hidden = im.nsfw && !showNsfw;
                return (
                  <a
                    key={j}
                    href={im.url}
                    target="_blank"
                    rel="noreferrer"
                    title={t("candidateOpenOriginal")}
                    className="relative min-w-0 flex-1"
                  >
                    <img
                      src={im.thumb || im.url}
                      alt=""
                      loading="lazy"
                      className={`h-full w-full object-cover ${hidden ? "blur-lg" : ""}`}
                    />
                    {hidden && (
                      <span className="absolute inset-0 flex items-center justify-center text-[10px] text-gray-300">
                        NSFW
                      </span>
                    )}
                  </a>
                );
              })}
            </div>
            <div className="flex flex-1 flex-col gap-1 p-2.5">
              <div className="flex items-start gap-1.5">
                <span className="text-xs text-gray-500">#{idx + 1}</span>
                <span className="line-clamp-2 flex-1 text-sm font-medium leading-snug text-gray-100">
                  {c.name}
                </span>
                {c.nsfw && (
                  <span className="shrink-0 rounded bg-red-900/50 px-1 py-0.5 text-[10px] text-red-300">
                    NSFW
                  </span>
                )}
              </div>
              <div className="flex flex-wrap gap-x-2 text-[11px] text-gray-400">
                <span>{c.type}</span>
                {c.base_model && <span>· {c.base_model}</span>}
                {c.downloads != null && <span>· ⬇ {fmt(c.downloads)}</span>}
                {c.size_kb && <span>· {(c.size_kb / 1024).toFixed(0)} MB</span>}
                {c.creator && <span>· {c.creator}</span>}
              </div>
              {(c.trained_words || []).length > 0 && (
                <div className="line-clamp-2 text-[11px] text-emerald-300/90" title={c.trained_words.join(", ")}>
                  {t("candidateTriggers")}: {c.trained_words.join(", ")}
                </div>
              )}
              <div className="mt-auto flex items-center gap-1.5 pt-1.5">
                <button
                  onClick={() => download(c)}
                  disabled={streaming}
                  data-testid="candidate-download"
                  className="flex items-center gap-1 rounded-md bg-emerald-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
                >
                  <Download size={13} /> {t("candidateDownload")}
                </button>
                <button
                  onClick={() => copyWords(c)}
                  title={t("candidateCopyWords")}
                  className="flex items-center gap-1 rounded-md border border-ink-600 px-2 py-1 text-xs text-gray-300 hover:bg-ink-750"
                >
                  {copied === c.id ? <Check size={13} /> : <Copy size={13} />}
                </button>
                <div className="flex-1" />
                <a
                  href={c.url}
                  target="_blank"
                  rel="noreferrer"
                  title="civitai.com"
                  className="text-gray-500 hover:text-gray-300"
                >
                  <ExternalLink size={14} />
                </a>
              </div>
            </div>
          </div>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-gray-500">{t("candidateHint")}</p>
    </div>
  );
}
