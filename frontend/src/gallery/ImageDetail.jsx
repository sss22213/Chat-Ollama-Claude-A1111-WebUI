import { useEffect, useState } from "react";
import {
  AlertTriangle,
  BookOpen,
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  Download,
  ExternalLink,
  FileText,
  Info,
  Link2,
  Loader2,
  MessageSquare,
  SlidersHorizontal,
  Tags,
  Trash2,
  Workflow,
  X,
} from "lucide-react";
import { useGallery } from "../store/gallery";
import { useChat } from "../store/chat";
import { useComic } from "../store/comic";
import { useWorkflow } from "../store/workflow";
import { formatBytes } from "../lib/galleryApi";
import { copyText } from "../lib/clipboard";
import { useGT, useLang } from "./galleryI18n";
import { useConfirmDelete } from "./useConfirmDelete";
import { navigate } from "../Root";

// 參數顯示順序固定，其餘照原順序接在後面
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

const iconBtn = "rounded-lg p-2 text-gray-300 hover:bg-white/10 disabled:opacity-30";

export default function ImageDetail() {
  const gt = useGT();
  const g = useGallery();
  const item = g.items.find((i) => i.name === g.detail);
  const idx = g.items.findIndex((i) => i.name === g.detail);
  const info = g.info;
  const confirmDelete = useConfirmDelete();
  const [delErr, setDelErr] = useState("");

  const del = async () => {
    setDelErr("");
    try {
      await confirmDelete([g.detail], info?.refs?.length ? 1 : item?.used ? 1 : 0);
    } catch (e) {
      setDelErr(e.message);
    }
  };

  // ← → 換圖、Esc 關閉、Delete 刪除（在輸入框裡打字時不攔）
  useEffect(() => {
    const onKey = (e) => {
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target?.tagName)) return;
      if (e.key === "Escape") g.closeDetail();
      else if (e.key === "ArrowLeft") g.step(-1);
      else if (e.key === "ArrowRight") g.step(1);
      else if (e.key === "Delete") del();
      else return;
      e.preventDefault();
      e.stopImmediatePropagation(); // 圖片庫的多選快捷鍵（Esc / Delete）不要再收到這一下
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const url = info?.url || `/images/${g.detail}`;
  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-black md:flex-row" data-testid="gal-detail">
      {/* 圖 */}
      <div className="relative flex min-h-0 flex-1 items-center justify-center p-2 md:p-4" onClick={g.closeDetail}>
        <img
          key={g.detail}
          src={url}
          alt={g.detail}
          onClick={(e) => e.stopPropagation()}
          className="max-h-full max-w-full object-contain"
          data-testid="gal-detail-img"
        />
        <button
          onClick={(e) => {
            e.stopPropagation();
            g.step(-1);
          }}
          disabled={idx <= 0}
          title={gt("prev")}
          data-testid="gal-prev"
          className="absolute left-1 top-1/2 -translate-y-1/2 rounded-full bg-black/50 p-2 text-white hover:bg-black/70 disabled:opacity-20"
        >
          <ChevronLeft size={22} />
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            g.step(1);
          }}
          disabled={idx < 0 || (idx >= g.items.length - 1 && g.items.length >= g.total)}
          title={gt("next")}
          data-testid="gal-next"
          className="absolute right-1 top-1/2 -translate-y-1/2 rounded-full bg-black/50 p-2 text-white hover:bg-black/70 disabled:opacity-20"
        >
          <ChevronRight size={22} />
        </button>
        <span className="pointer-events-none absolute bottom-2 left-1/2 -translate-x-1/2 rounded bg-black/50 px-2 py-0.5 text-xs text-gray-300">
          {idx + 1} / {g.total}
        </span>
      </div>

      {/* 資訊面板 */}
      <aside className="flex max-h-[55dvh] min-h-0 flex-col border-t border-ink-700 bg-ink-850 md:max-h-none md:w-[26rem] md:border-l md:border-t-0">
        <div className="flex items-center gap-1 border-b border-ink-700 px-2 py-1.5">
          <span className="min-w-0 flex-1 truncate px-1 font-mono text-xs text-gray-300" title={g.detail} data-testid="gal-detail-name">
            {g.detail}
          </span>
          <a href={url} target="_blank" rel="noreferrer" title={gt("openOriginal")} className={iconBtn}>
            <ExternalLink size={16} />
          </a>
          <a href={url} download={g.detail} title={gt("download")} className={iconBtn} data-testid="gal-download">
            <Download size={16} />
          </a>
          <button onClick={del} title={gt("delete")} className={`${iconBtn} text-red-300`} data-testid="gal-detail-delete">
            <Trash2 size={16} />
          </button>
          <button onClick={g.closeDetail} title={gt("close")} className={iconBtn} data-testid="gal-close">
            <X size={18} />
          </button>
        </div>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3 text-sm">
          {delErr && <Warn text={delErr} red />}
          {g.infoError && <Warn text={g.infoError} red />}
          {!info && !g.infoError && (
            <div className="flex items-center gap-2 py-6 text-gray-400">
              <Loader2 size={16} className="animate-spin" /> {gt("loading")}
            </div>
          )}
          {info && <InfoBody info={info} />}
        </div>
      </aside>
    </div>
  );
}

function InfoBody({ info }) {
  const gt = useGT();
  const lang = useLang();
  const parsed = info.parsed;
  const params = parsed?.params || {};
  const keys = [...PARAM_ORDER.filter((k) => k in params), ...Object.keys(params).filter((k) => !PARAM_ORDER.includes(k))];
  const exif = Object.entries(info.exif || {});
  const other = Object.entries(info.other || {});
  return (
    <>
      {/* 生成參數 */}
      <Section icon={<SlidersHorizontal size={14} />} title={gt("genParams")} testid="gal-params">
        {parsed ? (
          <div className="space-y-2">
            {parsed.prompt && <CopyField label="Prompt" value={parsed.prompt} testid="gal-prompt" />}
            {parsed.negative_prompt && <CopyField label="Negative prompt" value={parsed.negative_prompt} />}
            {keys.length > 0 && (
              <div className="grid grid-cols-2 gap-x-3 gap-y-1 rounded-lg bg-ink-900 p-2 text-xs" data-testid="gal-param-grid">
                {keys.map((k) => (
                  <div key={k} className="flex min-w-0 gap-1.5">
                    <span className="shrink-0 text-gray-500">{k}:</span>
                    <span className="text-gray-200 [overflow-wrap:anywhere]">{params[k]}</span>
                  </div>
                ))}
              </div>
            )}
            <ApplyButton settings={parsed.settings} />
          </div>
        ) : (
          <p className="text-xs text-gray-500">{gt("noMeta")}</p>
        )}
      </Section>

      {/* PNG 標籤（所有文字區塊） */}
      <Section icon={<Tags size={14} />} title={gt("pngTags")} testid="gal-tags">
        {info.texts.length ? (
          <div className="space-y-2">
            {info.texts.map((t) => (
              <TagField key={t.key} tag={t} />
            ))}
          </div>
        ) : (
          <p className="text-xs text-gray-500">{gt("noTags")}</p>
        )}
      </Section>

      {exif.length > 0 && (
        <Section icon={<FileText size={14} />} title={gt("exif")} testid="gal-exif">
          <KeyValues rows={exif} />
        </Section>
      )}

      {/* 檔案 */}
      <Section icon={<Info size={14} />} title={gt("file")} testid="gal-file">
        <KeyValues
          rows={[
            [gt("fileName"), info.name],
            [gt("location"), info.folder],
            [gt("dimensions"), `${info.w} × ${info.h}`],
            [gt("fileSize"), formatBytes(info.size)],
            [gt("format"), `${info.format || "?"} · ${info.mode || ""}`],
            [gt("modified"), new Date(info.mtime * 1000).toLocaleString(lang)],
            ...other,
          ]}
        />
      </Section>

      {/* 用在哪裡 */}
      <Section icon={<Link2 size={14} />} title={gt("usedIn")} testid="gal-refs">
        {info.refs.length ? (
          <ul className="space-y-1">
            {info.refs.map((r) => (
              <RefRow key={`${r.type}-${r.project || ""}-${r.id}`} r={r} />
            ))}
          </ul>
        ) : (
          <p className="text-xs text-gray-500">{gt("notUsed")}</p>
        )}
      </Section>
    </>
  );
}

function Section({ icon, title, children, testid }) {
  return (
    <section data-testid={testid}>
      <h3 className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-gray-400">
        {icon}
        {title}
      </h3>
      {children}
    </section>
  );
}

function KeyValues({ rows }) {
  return (
    <div className="divide-y divide-ink-700 rounded-lg bg-ink-900 text-xs">
      {rows.map(([k, v]) => (
        <div key={k} className="flex gap-2 px-2 py-1">
          <span className="w-24 shrink-0 text-gray-500">{k}</span>
          <span className="min-w-0 flex-1 whitespace-pre-wrap text-gray-200 [overflow-wrap:anywhere]">{String(v)}</span>
        </div>
      ))}
    </div>
  );
}

function useCopied() {
  const [copied, setCopied] = useState(false);
  const copy = async (text) => {
    if (!(await copyText(text))) return;
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return [copied, copy];
}

function CopyButton({ text }) {
  const gt = useGT();
  const [copied, copy] = useCopied();
  return (
    <button onClick={() => copy(text)} className="flex items-center gap-1 text-xs text-gray-400 hover:text-emerald-300">
      {copied ? <Check size={12} /> : <Copy size={12} />}
      {copied ? gt("copied") : gt("copy")}
    </button>
  );
}

function CopyField({ label, value, testid }) {
  return (
    <div className="rounded-lg bg-ink-900 p-2" data-testid={testid}>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-xs font-medium text-gray-500">{label}</span>
        <CopyButton text={value} />
      </div>
      <p className="max-h-36 overflow-auto whitespace-pre-wrap break-words text-xs leading-relaxed text-gray-200">{value}</p>
    </div>
  );
}

// 一個 PNG 文字區塊：JSON（例如 ComfyUI 的 prompt / workflow）排版後顯示
function TagField({ tag }) {
  const gt = useGT();
  const [open, setOpen] = useState(false);
  let shown = tag.value;
  try {
    const v = tag.value.trim();
    if (v.startsWith("{") || v.startsWith("[")) shown = JSON.stringify(JSON.parse(v), null, 2);
  } catch {
    /* 不是 JSON 就原樣顯示 */
  }
  return (
    <div className="rounded-lg bg-ink-900 p-2" data-testid="gal-tag" data-key={tag.key}>
      <div className="mb-1 flex items-center gap-2">
        <span className="font-mono text-xs font-semibold text-emerald-300">{tag.key}</span>
        <span className="text-[10px] text-gray-600">{gt("chars", { n: tag.length })}</span>
        <div className="flex-1" />
        <CopyButton text={tag.value} />
      </div>
      <pre
        className={`overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-gray-300 ${
          open ? "max-h-[60vh]" : "max-h-40"
        }`}
      >
        {shown}
      </pre>
      {shown.split("\n").length > 10 && (
        <button onClick={() => setOpen((v) => !v)} className="mt-1 text-[11px] text-gray-500 hover:text-gray-300">
          {open ? "▴" : `▾ ${gt("showAll")}`}
        </button>
      )}
      {tag.length > tag.value.length && <p className="mt-1 text-[10px] text-amber-300/80">{gt("truncated", { n: tag.value.length })}</p>}
    </div>
  );
}

// 跟 PNG Info 一樣：把這張圖的參數套到聊天頁的生圖設定（checkpoint 對不上已載入的模型就不套）
function ApplyButton({ settings }) {
  const gt = useGT();
  const setImageSettings = useChat((s) => s.setImageSettings);
  const sdModels = useChat((s) => s.sdModels);
  const [applied, setApplied] = useState(false);
  if (!settings || !Object.keys(settings).length) return null;
  const apply = () => {
    const s = { ...settings };
    if (s.sd_model_checkpoint && !sdModels.find((m) => m.model_name === s.sd_model_checkpoint)) delete s.sd_model_checkpoint;
    setImageSettings(s);
    setApplied(true);
  };
  return (
    <button
      onClick={apply}
      data-testid="gal-apply"
      className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium ${
        applied ? "bg-emerald-700/40 text-emerald-300" : "bg-emerald-600 text-white hover:bg-emerald-500"
      }`}
    >
      {applied ? <Check size={13} /> : <SlidersHorizontal size={13} />}
      {applied ? gt("applied") : gt("apply")}
    </button>
  );
}

function RefRow({ r }) {
  const gt = useGT();
  const icon =
    r.type === "chat" ? <MessageSquare size={13} /> : r.type === "comic" ? <BookOpen size={13} /> : <Workflow size={13} />;
  const open = async () => {
    useGallery.getState().closeDetail();
    if (r.type === "chat") {
      useChat.getState().selectConversation(r.id);
      navigate("");
    } else if (r.type === "comic") {
      const c = useComic.getState();
      if (c.projectId !== r.id) {
        await c.saveProject(); // 先存好目前的作品再換
        await c.openProject(r.id);
      }
      navigate("comic");
    } else {
      useWorkflow.getState().select?.(r.project);
      navigate("workflows");
    }
  };
  const title = r.type === "workflow" ? `${r.project} · ${r.id}` : r.title || gt("untitled");
  return (
    <li className="flex items-center gap-2 rounded-lg bg-ink-900 px-2 py-1.5 text-xs" data-testid="gal-ref">
      <span className="flex shrink-0 items-center gap-1 text-gray-400">
        {icon}
        {gt(`ref_${r.type}`)}
      </span>
      <span className="min-w-0 flex-1 truncate text-gray-200" title={title}>
        {title}
      </span>
      <button onClick={open} className="shrink-0 rounded border border-ink-600 px-2 py-0.5 text-gray-300 hover:bg-ink-750" data-testid="gal-ref-open">
        {gt("open")}
      </button>
    </li>
  );
}

function Warn({ text, red }) {
  return (
    <div
      className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-xs ${
        red ? "border-red-900/50 bg-red-950/40 text-red-300" : "border-amber-900/50 bg-amber-950/30 text-amber-200"
      }`}
    >
      <AlertTriangle size={14} className="mt-0.5 shrink-0" />
      <span className="break-words">{text}</span>
    </div>
  );
}
