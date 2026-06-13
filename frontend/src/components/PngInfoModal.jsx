import { useEffect, useState } from "react";
import {
  X,
  FileText,
  Copy,
  Check,
  Loader2,
  AlertTriangle,
  SlidersHorizontal,
} from "lucide-react";
import { useChat } from "../store/chat";
import { useT } from "../i18n";
import { readPngInfo } from "../lib/api";

const blobToDataUrl = (blob) =>
  new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = reject;
    r.readAsDataURL(blob);
  });

// image：data: URL（上傳原圖）或一般 URL（後端生成圖）。
async function resolveDataUrl(image) {
  if (image.startsWith("data:")) return image;
  const resp = await fetch(image);
  return blobToDataUrl(await resp.blob());
}

// 顯示順序固定，避免每次 key 順序亂跳。
const PARAM_ORDER = [
  "Steps",
  "Sampler",
  "Schedule type",
  "CFG scale",
  "Seed",
  "Size",
  "Model",
  "Model hash",
  "Denoising strength",
  "Clip skip",
  "VAE",
];

export default function PngInfoModal({ image, onClose }) {
  const t = useT();
  const setImageSettings = useChat((s) => s.setImageSettings);
  const sdModels = useChat((s) => s.sdModels);

  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [data, setData] = useState(null);
  const [preview, setPreview] = useState("");
  const [applied, setApplied] = useState(false);
  const [showRaw, setShowRaw] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const dataUrl = await resolveDataUrl(image);
        if (!alive) return;
        setPreview(dataUrl);
        const info = await readPngInfo(dataUrl);
        if (alive) setData(info);
      } catch (e) {
        if (alive) setErr(e.message);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [image]);

  const apply = () => {
    const s = { ...(data.settings || {}) };
    // checkpoint 名稱對不上已載入的 SD 模型時就不套用（避免下拉變空）
    if (
      s.sd_model_checkpoint &&
      !sdModels.find((m) => m.model_name === s.sd_model_checkpoint)
    ) {
      delete s.sd_model_checkpoint;
    }
    setImageSettings(s);
    setApplied(true);
  };

  const params = data?.params || {};
  const orderedKeys = [
    ...PARAM_ORDER.filter((k) => k in params),
    ...Object.keys(params).filter((k) => !PARAM_ORDER.includes(k)),
  ];
  const hasInfo = !!data?.info;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-ink-700 bg-ink-850"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-ink-700 px-5 py-3">
          <h2 className="flex items-center gap-2 text-base font-semibold">
            <FileText size={17} /> {t("pngInfo")}
          </h2>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-gray-400 hover:bg-ink-750"
          >
            <X size={18} />
          </button>
        </div>

        <div className="space-y-3 overflow-y-auto px-5 py-4">
          {preview && (
            <img
              src={preview}
              alt="preview"
              className="mx-auto max-h-40 rounded-lg border border-ink-700 object-contain"
            />
          )}

          {loading && (
            <div className="flex items-center justify-center gap-2 py-6 text-sm text-gray-400">
              <Loader2 size={16} className="animate-spin" /> {t("pngReading")}
            </div>
          )}

          {err && (
            <div className="flex items-start gap-2 rounded-lg border border-red-900/50 bg-red-950/40 px-3 py-2 text-sm text-red-300">
              <AlertTriangle size={15} className="mt-0.5 shrink-0" />
              <span>{err}</span>
            </div>
          )}

          {!loading && !err && !hasInfo && (
            <div className="flex items-start gap-2 rounded-lg border border-amber-900/50 bg-amber-950/30 px-3 py-2.5 text-sm text-amber-200/90">
              <AlertTriangle size={15} className="mt-0.5 shrink-0" />
              <span>{t("pngNone")}</span>
            </div>
          )}

          {!loading && hasInfo && (
            <>
              {data.prompt && (
                <FieldCopy label="Prompt" value={data.prompt} t={t} />
              )}
              {data.negative_prompt && (
                <FieldCopy
                  label="Negative prompt"
                  value={data.negative_prompt}
                  t={t}
                />
              )}

              {orderedKeys.length > 0 && (
                <div className="grid grid-cols-2 gap-x-4 gap-y-1 rounded-lg bg-ink-850 p-2.5 text-xs">
                  {orderedKeys.map((k) => (
                    <div key={k} className="flex gap-1.5">
                      <span className="shrink-0 font-medium text-gray-500">
                        {k}:
                      </span>
                      <span className="break-all text-gray-200">
                        {params[k]}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              <button
                onClick={() => setShowRaw((v) => !v)}
                className="text-xs text-gray-500 hover:text-gray-300"
              >
                {showRaw ? "▾" : "▸"} {t("pngRaw")}
              </button>
              {showRaw && (
                <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded-lg bg-ink-900 p-2.5 text-[11px] leading-relaxed text-gray-400">
                  {data.info}
                </pre>
              )}
            </>
          )}
        </div>

        {!loading && hasInfo && (
          <div className="flex items-center justify-end gap-2 border-t border-ink-700 px-5 py-3">
            <button
              onClick={apply}
              className={`flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium transition ${
                applied
                  ? "bg-emerald-700/40 text-emerald-300"
                  : "bg-emerald-600 text-white hover:bg-emerald-500"
              }`}
            >
              {applied ? <Check size={15} /> : <SlidersHorizontal size={15} />}
              {applied ? t("pngApplied") : t("pngApply")}
            </button>
          </div>
        )}
      </div>
    </div>
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
    <div className="rounded-lg bg-ink-850 p-2.5">
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
      <p className="max-h-28 overflow-auto whitespace-pre-wrap break-words text-xs leading-relaxed text-gray-200">
        {value}
      </p>
    </div>
  );
}
