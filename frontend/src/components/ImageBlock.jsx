import { useState } from "react";
import {
  Download,
  Maximize2,
  X,
  Info,
  Paintbrush,
  FileText,
} from "lucide-react";
import { useChat } from "../store/chat";
import { useT } from "../i18n";
import PngInfoModal from "./PngInfoModal";

const blobToDataUrl = (blob) =>
  new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = reject;
    r.readAsDataURL(blob);
  });

export default function ImageBlock({ img }) {
  const t = useT();
  const [zoom, setZoom] = useState(false);
  const [showParams, setShowParams] = useState(false);
  const [pngInfo, setPngInfo] = useState(false);
  const addAttachment = useChat((s) => s.addAttachment);
  const p = img.params || {};

  const useAsInit = async () => {
    try {
      const resp = await fetch(img.url);
      const dataUrl = await blobToDataUrl(await resp.blob());
      addAttachment(dataUrl);
    } catch {
      /* 忽略 */
    }
  };

  return (
    <div className="inline-block max-w-md">
      <div className="group relative overflow-hidden rounded-xl border border-ink-700 bg-ink-850">
        <img
          src={img.url}
          alt={p.prompt || "generated"}
          onClick={() => setZoom(true)}
          className="block max-h-[28rem] w-full cursor-zoom-in object-contain"
        />
        {p.mode === "img2img" && (
          <span className="absolute left-2 top-2 rounded-md bg-black/60 px-1.5 py-0.5 text-[11px] text-emerald-300">
            img2img
          </span>
        )}
        <div className="absolute right-2 top-2 flex gap-1 opacity-0 transition group-hover:opacity-100">
          <IconBtn title={t("redraw")} onClick={useAsInit}>
            <Paintbrush size={15} />
          </IconBtn>
          <IconBtn title={t("zoom")} onClick={() => setZoom(true)}>
            <Maximize2 size={15} />
          </IconBtn>
          <IconBtn title={t("viewParams")} onClick={() => setShowParams((v) => !v)}>
            <Info size={15} />
          </IconBtn>
          <IconBtn title={t("pngInfo")} onClick={() => setPngInfo(true)}>
            <FileText size={15} />
          </IconBtn>
          <a
            href={img.url}
            download
            className="rounded-md bg-black/60 p-1.5 text-white hover:bg-black/80"
            title={t("download")}
          >
            <Download size={15} />
          </a>
        </div>
      </div>

      {showParams && (
        <div className="mt-1.5 space-y-0.5 rounded-lg bg-ink-850 p-2.5 text-xs text-gray-400">
          <Row label={t("modeLabel")} value={p.mode || "txt2img"} />
          <Row label="Prompt" value={p.prompt} />
          {p.negative_prompt ? (
            <Row label="Negative" value={p.negative_prompt} />
          ) : null}
          <Row
            label={t("paramsLabel")}
            value={`${p.width}×${p.height} · ${p.sampler_name} · ${p.steps} steps · CFG ${p.cfg_scale} · seed ${p.seed}`}
          />
          {p.denoising_strength != null ? (
            <Row label="Denoise" value={p.denoising_strength} />
          ) : null}
          {p.sd_model_checkpoint ? (
            <Row label="Model" value={p.sd_model_checkpoint} />
          ) : null}
        </div>
      )}

      {pngInfo && (
        <PngInfoModal image={img.url} onClose={() => setPngInfo(false)} />
      )}

      {zoom && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-6"
          onClick={() => setZoom(false)}
        >
          <button
            className="absolute right-5 top-5 rounded-lg p-2 text-white hover:bg-white/10"
            onClick={() => setZoom(false)}
          >
            <X size={22} />
          </button>
          <img
            src={img.url}
            alt={p.prompt || "generated"}
            className="max-h-full max-w-full rounded-lg object-contain"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}
    </div>
  );
}

function IconBtn({ children, ...rest }) {
  return (
    <button
      className="rounded-md bg-black/60 p-1.5 text-white hover:bg-black/80"
      {...rest}
    >
      {children}
    </button>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex gap-2">
      <span className="shrink-0 font-medium text-gray-500">{label}:</span>
      <span className="break-words">{value}</span>
    </div>
  );
}
