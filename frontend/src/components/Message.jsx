import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import {
  ChevronRight,
  Brain,
  Loader2,
  AlertTriangle,
  User,
  Globe,
  ExternalLink,
  Combine,
  FileText,
} from "lucide-react";
import ImageBlock from "./ImageBlock";
import { useT } from "../i18n";

export default function Message({ msg }) {
  const isUser = msg.role === "user";

  if (isUser) {
    return (
      <div className="mb-6 flex justify-end">
        <div className="flex max-w-[85%] items-start gap-3">
          <div className="flex flex-col items-end gap-1.5">
            {(msg.attachments || []).length > 0 && (
              <div className="flex flex-wrap justify-end gap-1.5">
                {msg.attachments.map((a, i) => (
                  <img
                    key={i}
                    src={a.dataUrl}
                    alt="attachment"
                    className="h-28 w-28 rounded-xl border border-ink-600 object-cover"
                  />
                ))}
              </div>
            )}
            {msg.content && (
              <div className="whitespace-pre-wrap rounded-2xl rounded-tr-sm bg-ink-700 px-4 py-2.5 text-[0.95rem] leading-relaxed">
                {msg.content}
              </div>
            )}
          </div>
          <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-ink-600">
            <User size={15} />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="mb-6 flex gap-3">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-600/20 text-emerald-400">
        <span className="text-xs font-bold">AI</span>
      </div>
      <div className="min-w-0 flex-1 space-y-2">
        {msg.compacted && <CompactBadge />}

        {msg.thinking ? (
          <Thinking text={msg.thinking} streaming={msg.status === "streaming"} />
        ) : null}

        {msg.toolRunning &&
          (msg.toolName === "web_search" || msg.toolName === "fetch_url" ? (
            <WebActivity toolName={msg.toolName} />
          ) : msg.toolName === "read_png_info" ? (
            <PngInfoActivity />
          ) : (
            <GenProgress
              progress={msg.progress}
              editing={msg.toolName === "edit_image"}
            />
          ))}

        {msg.content ? (
          <div className="markdown text-[0.95rem]">
            <Markdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeHighlight]}
            >
              {msg.content}
            </Markdown>
          </div>
        ) : null}

        {(msg.images || []).map((img, i) => (
          <ImageBlock key={i} img={img} />
        ))}

        {(msg.sources || []).length > 0 && <Sources sources={msg.sources} />}

        {msg.error && (
          <div className="flex items-start gap-2 rounded-lg border border-red-900/50 bg-red-950/40 px-3 py-2 text-sm text-red-300">
            <AlertTriangle size={15} className="mt-0.5 shrink-0" />
            <span>{msg.error}</span>
          </div>
        )}

        {msg.status === "streaming" &&
          !msg.content &&
          !msg.thinking &&
          !msg.toolRunning && (
            <StreamingDots />
          )}
      </div>
    </div>
  );
}

function StreamingDots() {
  const t = useT();
  return (
    <div className="flex items-center gap-2 text-sm text-gray-500">
      <Loader2 size={14} className="animate-spin" /> {t("thinkingDots")}
    </div>
  );
}

function CompactBadge() {
  const t = useT();
  return (
    <div className="inline-flex items-center gap-1.5 rounded-md bg-ink-700 px-2 py-0.5 text-xs text-gray-300">
      <Combine size={13} /> {t("summaryBadge")}
    </div>
  );
}

function PngInfoActivity() {
  const t = useT();
  return (
    <div className="flex items-center gap-2 rounded-lg bg-ink-800 px-3 py-2 text-sm text-gray-300">
      <Loader2 size={15} className="animate-spin" />
      <FileText size={14} />
      {t("pngReading")}
    </div>
  );
}

function WebActivity({ toolName }) {
  const t = useT();
  return (
    <div className="flex items-center gap-2 rounded-lg bg-ink-800 px-3 py-2 text-sm text-sky-300">
      <Loader2 size={15} className="animate-spin" />
      <Globe size={14} />
      {toolName === "fetch_url" ? t("readingPage") : t("searching")}
    </div>
  );
}

function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function Sources({ sources }) {
  const t = useT();
  return (
    <div className="space-y-1.5 rounded-lg border border-ink-700 bg-ink-850 p-2.5">
      <div className="flex items-center gap-1.5 text-xs font-medium text-gray-400">
        <Globe size={13} /> {t("sourcesLabel")} · {sources.length}
      </div>
      <div className="flex flex-col gap-1">
        {sources.map((s, i) => (
          <a
            key={i}
            href={s.url}
            target="_blank"
            rel="noreferrer"
            title={s.snippet || s.url}
            className="group flex items-start gap-1.5 text-xs text-gray-300 hover:text-sky-300"
          >
            <span className="mt-0.5 w-4 shrink-0 text-right text-gray-500">
              {i + 1}.
            </span>
            <ExternalLink size={12} className="mt-0.5 shrink-0 text-gray-500" />
            <span className="truncate">
              <span className="text-gray-200 group-hover:text-sky-300">
                {s.title || hostOf(s.url)}
              </span>
              <span className="ml-1.5 text-gray-500">{hostOf(s.url)}</span>
            </span>
          </a>
        ))}
      </div>
    </div>
  );
}

function GenProgress({ progress, editing }) {
  const t = useT();
  const pct = Math.round((progress?.value || 0) * 100);
  const label = editing ? t("redrawing") : t("generating");
  return (
    <div className="max-w-md space-y-2 rounded-xl border border-ink-700 bg-ink-850 p-3">
      <div className="flex items-center gap-2 text-sm text-emerald-300">
        <Loader2 size={15} className="animate-spin" />
        {label}…
        <span className="ml-auto tabular-nums text-gray-400">
          {pct}%
          {progress?.steps
            ? ` · ${progress.step ?? 0}/${progress.steps} ${t("stepsUnit")}`
            : ""}
        </span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-ink-700">
        <div
          className="h-full rounded-full bg-emerald-500 transition-all duration-300"
          style={{ width: `${Math.max(pct, 3)}%` }}
        />
      </div>
      {progress?.preview && (
        <img
          src={progress.preview}
          alt="預覽"
          className="mt-1 max-h-72 w-full rounded-lg object-contain opacity-90"
        />
      )}
    </div>
  );
}

function Thinking({ text, streaming }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-ink-700 bg-ink-850">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-xs text-gray-400 hover:text-gray-200"
      >
        <ChevronRight
          size={14}
          className={`transition-transform ${open ? "rotate-90" : ""}`}
        />
        <Brain size={14} />
        {t("thinkingTitle")}
        {streaming && <Loader2 size={12} className="animate-spin" />}
      </button>
      {open && (
        <div className="whitespace-pre-wrap border-t border-ink-700 px-3 py-2 text-xs leading-relaxed text-gray-400">
          {text}
        </div>
      )}
    </div>
  );
}
