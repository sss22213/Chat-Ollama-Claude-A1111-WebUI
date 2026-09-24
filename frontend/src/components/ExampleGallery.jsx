import { useState } from "react";
import { Copy, Check, EyeOff, HardDrive, Globe, ChevronDown, ChevronUp } from "lucide-react";
import { useT } from "../i18n";

/**
 * 技能工具回傳的範例圖庫（Civitai Helper：本地存好的範例圖優先、其次 civitai 縮圖）。
 * 每張：縮圖（點開原圖）、提示詞（可展開 / 複製）、負面提示詞與生成參數。NSFW 預設直接顯示（可切換隱藏）。
 */
export default function ExampleGallery({ gallery }) {
  const t = useT();
  const [showNsfw, setShowNsfw] = useState(true); // 預設直接顯示 NSFW（不模糊），按鈕可切換隱藏
  const [open, setOpen] = useState(null); // 展開提示詞的 index
  const [copied, setCopied] = useState(null);
  const items = gallery?.items || [];
  if (!items.length) return null;

  const copy = async (key, text) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
      setTimeout(() => setCopied(null), 1500);
    } catch {
      /* 剪貼簿不可用 */
    }
  };
  const params = (p) =>
    Object.entries(p || {})
      .map(([k, v]) => `${k.replace("_", " ")} ${v}`)
      .join(" · ");

  return (
    <div data-testid="gallery" className="rounded-xl border border-ink-700 bg-ink-850 p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-gray-400">
        <span className="font-medium text-gray-200">{gallery.title}</span>
        <span>{t("galleryCount", { count: items.length })}</span>
        <div className="flex-1" />
        {items.some((it) => it.nsfw) && (
          <button
            onClick={() => setShowNsfw((v) => !v)}
            className="flex items-center gap-1 rounded border border-ink-600 px-1.5 py-0.5 hover:bg-ink-750"
          >
            <EyeOff size={12} /> {showNsfw ? t("candidateHideNsfw") : t("candidateShowNsfw")}
          </button>
        )}
      </div>
      {(gallery.trained_words || []).length > 0 && (
        <div className="mb-2 flex items-center gap-1.5 text-[11px] text-emerald-300/90">
          <span className="min-w-0 flex-1 truncate" title={gallery.trained_words.join(", ")}>
            {t("candidateTriggers")}: {gallery.trained_words.join(", ")}
          </span>
          <button
            onClick={() => copy("tw", gallery.trained_words.join(", "))}
            title={t("galleryCopy")}
            className="shrink-0 text-gray-400 hover:text-gray-200"
          >
            {copied === "tw" ? <Check size={13} /> : <Copy size={13} />}
          </button>
        </div>
      )}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
        {items.map((it, i) => {
          const hidden = it.nsfw && !showNsfw;
          const expanded = open === i;
          return (
            <div
              key={`${it.index}-${i}`}
              data-testid="gallery-item"
              className="flex flex-col overflow-hidden rounded-lg border border-ink-700 bg-ink-800"
            >
              <a href={it.full} target="_blank" rel="noreferrer" className="relative block aspect-square bg-ink-900" title={t("candidateOpenOriginal")}>
                <img
                  src={it.src}
                  alt={`#${it.index}`}
                  loading="lazy"
                  className={`h-full w-full object-cover ${hidden ? "blur-xl" : ""}`}
                />
                <span className="absolute left-1 top-1 flex items-center gap-1 rounded bg-black/60 px-1 py-0.5 text-[10px] text-gray-200">
                  #{it.index}
                  {it.local ? <HardDrive size={10} /> : <Globe size={10} />}
                </span>
                {hidden && (
                  <span className="absolute inset-0 flex items-center justify-center text-[11px] text-gray-200">NSFW</span>
                )}
              </a>
              <div className="flex flex-1 flex-col gap-1 p-2">
                {it.prompt ? (
                  <p className={`text-[11px] leading-snug text-gray-300 ${expanded ? "" : "line-clamp-3"}`}>{it.prompt}</p>
                ) : (
                  <p className="text-[11px] text-gray-600">{t("galleryNoPrompt")}</p>
                )}
                {expanded && it.negative_prompt && (
                  <p className="text-[11px] leading-snug text-red-300/80">− {it.negative_prompt}</p>
                )}
                {expanded && Object.keys(it.params || {}).length > 0 && (
                  <p className="text-[10px] text-gray-500">{params(it.params)}</p>
                )}
                <div className="mt-auto flex items-center gap-2 pt-1 text-gray-400">
                  {it.prompt && (
                    <button
                      onClick={() => copy(i, it.prompt)}
                      title={t("galleryCopy")}
                      data-testid="gallery-copy"
                      className="hover:text-gray-200"
                    >
                      {copied === i ? <Check size={13} /> : <Copy size={13} />}
                    </button>
                  )}
                  <div className="flex-1" />
                  {(it.prompt || it.negative_prompt) && (
                    <button onClick={() => setOpen(expanded ? null : i)} className="hover:text-gray-200" title={t("galleryDetails")}>
                      {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                    </button>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
