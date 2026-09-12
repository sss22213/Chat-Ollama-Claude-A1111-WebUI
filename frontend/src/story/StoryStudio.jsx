import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Images,
  ImagePlus,
  X,
  Loader2,
  Wand2,
  Copy,
  Check,
  BookOpen,
  Settings,
  RefreshCw,
  AlertCircle,
  Play,
  Gauge,
  ChevronLeft,
  ChevronRight,
  LayoutGrid,
} from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useStory, estimateTokens } from "../store/story";
import { useChat } from "../store/chat";
import { useComic } from "../store/comic";
import { noticeText } from "../comic/notices";
import { useST } from "./storyI18n";
import { useT } from "../i18n";
import { navigate } from "../Root";
import { readAsDataUrl, imageFilesFrom } from "../lib/image";
import SettingsModal from "../components/SettingsModal";

const inputCls =
  "w-full rounded-md border border-ink-600 bg-ink-800 px-2 py-1.5 text-sm outline-none focus:border-ink-500";

function CopyBtn({ text, st }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      setTimeout(() => setDone(false), 1500);
    } catch {
      /* 忽略 */
    }
  };
  return (
    <button
      onClick={copy}
      className="flex items-center gap-1 rounded-md border border-ink-600 px-2 py-1 text-xs text-gray-300 hover:bg-ink-750"
    >
      {done ? <Check size={13} /> : <Copy size={13} />}
      {done ? st("copied") : st("copy")}
    </button>
  );
}

export default function StoryStudio() {
  const st = useST();
  const t = useT();
  const s = useStory();
  const models = useChat((c) => c.models);
  const engine = useChat((c) => c.settings.engine);
  const engines = useChat((c) => c.engines);
  const setEngine = useChat((c) => c.setEngine);
  const chatModel = useChat((c) => c.settings.chatModel);
  const setSettings = useChat((c) => c.setSettings);
  const lang = useChat((c) => c.settings.lang);
  const numCtx = useChat((c) => c.settings.numCtx);
  const health = useChat((c) => c.health);
  const importScript = useComic((c) => c.importScript);

  const fileRef = useRef(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  const model = chatModel;
  const modelMeta = models.find((m) => m.name === model);
  const noVision = !!modelMeta && modelMeta.supports_vision === false;

  // context 預估：Ollama 以設定的 num_ctx 為上限；CLI 引擎用模型本身的 context 長度
  const ctxLimit =
    engine === "ollama" ? Number(numCtx) || 0 : Number(modelMeta?.context_length) || 0;
  const estTokens = estimateTokens({
    count: s.images.length,
    mode: s.mode,
    length: s.length,
    panelCount: s.panelCount,
  });
  const ctxOver = ctxLimit > 0 && s.images.length > 0 && estTokens > ctxLimit;
  const fmtK = (n) => (n >= 1000 ? `${(n / 1000).toFixed(n % 1000 ? 1 : 0)}k` : String(n));

  const addFiles = async (files) => {
    const imgs = imageFilesFrom(files);
    const urls = [];
    for (const f of imgs) {
      try {
        urls.push(await readAsDataUrl(f));
      } catch {
        /* 略過壞檔 */
      }
    }
    if (urls.length) useStory.getState().addImages(urls);
  };

  // 貼上圖片（整頁監聽）
  useEffect(() => {
    const onPaste = (e) => {
      const files = imageFilesFrom(e.clipboardData?.files);
      if (files.length) {
        e.preventDefault();
        addFiles(files);
      }
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, []);

  const onDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    addFiles(e.dataTransfer?.files);
  };

  const onGenerate = () => s.generate({ engine, model, lang, numCtx });

  // 送到漫畫工作室：漫畫腳本 → 整份匯入（角色卡 + 分鏡）；故事 → 當劇情大綱
  const toComic = (render) => {
    const r = s.result;
    if (!r) return;
    if (r.mode === "comic") {
      importScript({
        title: r.title,
        premise: r.premise,
        style: r.style,
        characters: r.characters,
        panels: r.panels,
      });
    } else if (r.mode === "panels") {
      // 每格帶上傳圖與 AI 補的對白／旁白；場景說明放在 prompt 當備註
      importScript({
        title: r.title,
        premise: r.premise,
        characters: [],
        panels: r.panels.map((p) => ({
          prompt: p.scene || "",
          dialogue: p.dialogue,
          caption: p.caption,
          image_url: p.image_url,
        })),
      });
    } else {
      importScript({ title: r.title, premise: r.story, characters: [], panels: [] });
    }
    navigate("comic");
    if (render && r.mode === "comic") {
      setTimeout(() => useComic.getState().generateAll(), 50);
    }
  };

  const r = s.result;

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-ink-900 text-[#ececec]">
      {/* 頂列 */}
      <header className="flex items-center gap-1.5 border-b border-ink-700 bg-ink-850 px-2 py-2 sm:gap-2 sm:px-3">
        <button
          onClick={() => navigate("")}
          title={st("backToChat")}
          className="shrink-0 rounded-lg p-2 text-gray-400 hover:bg-ink-750"
        >
          <ArrowLeft size={18} />
        </button>
        <h1 className="flex shrink-0 items-center gap-1.5 text-sm font-semibold">
          <Images size={17} />
          <span className="hidden sm:inline">{st("storyTitle")}</span>
        </h1>

        {/* 引擎 + 模型（沿用聊天頁的選擇） */}
        <select
          value={engine}
          onChange={(e) => setEngine(e.target.value)}
          title={st("engine")}
          className="shrink-0 rounded-lg border border-ink-600 bg-ink-800 px-2 py-1.5 text-sm outline-none focus:border-ink-500"
        >
          <option value="ollama">Ollama</option>
          <option value="claude_cli" disabled={!engines.claude_cli}>
            Claude CLI
          </option>
          <option value="codex" disabled={!engines.codex}>
            Codex CLI
          </option>
        </select>
        <select
          value={chatModel}
          onChange={(e) => setSettings({ chatModel: e.target.value })}
          className="min-w-0 max-w-[34vw] truncate rounded-lg border border-ink-600 bg-ink-800 px-2 py-1.5 text-sm outline-none focus:border-ink-500 sm:max-w-[16rem]"
        >
          {models.length === 0 && <option>{chatModel || "—"}</option>}
          {models.map((m) => (
            <option key={m.name} value={m.name}>
              {(m.supports_vision ? "👁 " : "") + m.name}
            </option>
          ))}
        </select>

        <div className="flex-1" />

        <button
          onClick={() => navigate("comic")}
          className="flex shrink-0 items-center gap-1.5 rounded-lg border border-ink-600 px-2 py-1.5 text-sm text-gray-300 hover:bg-ink-750 sm:px-3"
          title={st("toComic")}
        >
          <BookOpen size={16} />
          <span className="hidden md:inline">{st("toComic")}</span>
        </button>
        <button
          onClick={() => setSettingsOpen(true)}
          className="shrink-0 rounded-lg p-2 text-gray-400 hover:bg-ink-750"
          title={t("settings")}
        >
          <Settings size={18} />
        </button>
      </header>

      {/* 內容：手機直向堆疊整頁捲動；lg 以上左右兩欄各自捲動 */}
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto lg:flex-row lg:overflow-hidden">
        <aside className="shrink-0 space-y-3 border-b border-ink-700 p-3 lg:w-[380px] lg:overflow-y-auto lg:border-b-0 lg:border-r">
          {/* 上傳區 */}
          <div
            onClick={() => fileRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            className={`flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded-xl border border-dashed px-3 py-6 text-center text-sm transition ${
              dragOver
                ? "border-emerald-500 bg-emerald-500/10 text-emerald-200"
                : "border-ink-600 text-gray-400 hover:bg-ink-850"
            }`}
          >
            <ImagePlus size={22} />
            <span className="font-medium text-gray-200">{st("upload")}</span>
            <span className="text-xs text-gray-500">{st("uploadHint")}</span>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              onChange={(e) => {
                addFiles(e.target.files);
                e.target.value = "";
              }}
            />
          </div>

          {s.images.length > 0 && (
            <div className="space-y-2">
              <div className="grid grid-cols-4 gap-2 sm:grid-cols-5">
                {s.images.map((img, i) => (
                  <div
                    key={img.id}
                    className="relative aspect-square overflow-hidden rounded-lg border border-ink-700 bg-ink-850"
                  >
                    <img
                      src={img.dataUrl}
                      alt=""
                      className="h-full w-full object-cover"
                    />
                    <span className="absolute left-1 top-1 rounded bg-black/70 px-1.5 text-[11px] font-semibold text-white">
                      {i + 1}
                    </span>
                    <button
                      onClick={() => s.removeImage(img.id)}
                      className="absolute right-1 top-1 rounded-full bg-black/70 p-1 text-white hover:bg-red-600"
                    >
                      <X size={12} />
                    </button>
                    {/* 分鏡模式：順序即閱讀順序 */}
                    {s.mode === "panels" && s.images.length > 1 && (
                      <div className="absolute inset-x-0 bottom-0 flex justify-between bg-gradient-to-t from-black/70 to-transparent p-0.5">
                        <button
                          onClick={() => s.moveImage(img.id, -1)}
                          disabled={i === 0}
                          title={st("moveLeft")}
                          className="rounded p-0.5 text-white hover:bg-white/20 disabled:opacity-30"
                        >
                          <ChevronLeft size={14} />
                        </button>
                        <button
                          onClick={() => s.moveImage(img.id, 1)}
                          disabled={i === s.images.length - 1}
                          title={st("moveRight")}
                          className="rounded p-0.5 text-white hover:bg-white/20 disabled:opacity-30"
                        >
                          <ChevronRight size={14} />
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
              {s.mode === "panels" && s.images.length > 1 && (
                <p className="text-[11px] text-gray-500">{st("orderHint")}</p>
              )}
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-gray-500">
                  {st("imagesCount", { n: s.images.length })}
                </span>
                <button
                  onClick={() => fileRef.current?.click()}
                  className="rounded-md border border-ink-600 px-2 py-1 text-xs text-gray-300 hover:bg-ink-750"
                >
                  {st("addMore")}
                </button>
                <button
                  onClick={s.clearImages}
                  className="rounded-md border border-ink-600 px-2 py-1 text-xs text-gray-400 hover:bg-ink-750"
                >
                  {st("clearImages")}
                </button>
              </div>
            </div>
          )}

          {/* 模式 */}
          <div>
            <div className="mb-1 text-xs font-medium text-gray-400">{st("mode")}</div>
            <div className="grid grid-cols-3 gap-1.5">
              {[
                ["story", "modeStory"],
                ["comic", "modeComic"],
                ["panels", "modePanels"],
              ].map(([v, k]) => (
                <button
                  key={v}
                  onClick={() => s.set({ mode: v })}
                  className={`rounded-lg border px-2 py-1.5 text-sm transition ${
                    s.mode === v
                      ? "border-emerald-600/60 bg-emerald-600/20 text-emerald-200"
                      : "border-ink-600 text-gray-300 hover:bg-ink-750"
                  }`}
                >
                  {st(k)}
                </button>
              ))}
            </div>
            <p className="mt-1 text-[11px] leading-relaxed text-gray-500">
              {st(
                s.mode === "comic"
                  ? "modeComicHint"
                  : s.mode === "panels"
                  ? "modePanelsHint"
                  : "modeStoryHint"
              )}
            </p>
          </div>

          {/* 選項 */}
          {s.mode === "panels" ? null : s.mode === "story" ? (
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-gray-400">
                {st("length")}
              </span>
              <select
                value={s.length}
                onChange={(e) => s.set({ length: e.target.value })}
                className={inputCls}
              >
                <option value="short">{st("lenShort")}</option>
                <option value="medium">{st("lenMedium")}</option>
                <option value="long">{st("lenLong")}</option>
              </select>
            </label>
          ) : (
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-gray-400">
                {st("panelCount")}
              </span>
              <input
                type="number"
                min={1}
                max={16}
                value={s.panelCount}
                onChange={(e) =>
                  s.set({
                    panelCount: Math.max(1, Math.min(16, Number(e.target.value) || 6)),
                  })
                }
                className={inputCls}
              />
            </label>
          )}

          <label className="block">
            <span className="mb-1 block text-xs font-medium text-gray-400">
              {st("instructions")}
            </span>
            <textarea
              value={s.instructions}
              onChange={(e) => s.set({ instructions: e.target.value })}
              placeholder={st("instructionsPh")}
              rows={3}
              className={`${inputCls} resize-y`}
            />
          </label>

          {/* context 預估：圖片不限張數，但超過 context 請使用者自己減圖或調 num_ctx */}
          {s.images.length > 0 && (
            <div
              className={`space-y-1 rounded-lg border px-2 py-1.5 text-xs ${
                ctxOver
                  ? "border-red-800/60 bg-red-950/40 text-red-200"
                  : "border-ink-700 bg-ink-850 text-gray-400"
              }`}
            >
              <div className="flex items-center gap-1.5">
                <Gauge size={14} className="shrink-0" />
                <span className="min-w-0 flex-1">
                  {st("ctxEstimate", {
                    tokens: fmtK(estTokens),
                    limit: ctxLimit ? fmtK(ctxLimit) : "?",
                  })}
                </span>
                {engine === "ollama" && (
                  <button
                    onClick={() => setSettingsOpen(true)}
                    className="shrink-0 rounded-md border border-current/40 px-1.5 py-0.5 text-[11px] hover:bg-white/5"
                  >
                    {st("adjustCtx")}
                  </button>
                )}
              </div>
              {ctxOver && (
                <p className="leading-relaxed">
                  {st(engine === "ollama" ? "ctxOverOllama" : "ctxOverCli")}
                </p>
              )}
            </div>
          )}

          {engine === "ollama" && (
                  <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-ink-700 bg-ink-850 px-2 py-1.5">
                    <input
                      type="checkbox"
                      checked={!!s.think}
                      onChange={(e) => s.set({ think: e.target.checked })}
                      className="mt-0.5 shrink-0 accent-emerald-500"
                    />
                    <span className="min-w-0 text-xs">
                      <span className="text-gray-200">{st("thinkLabel")}</span>
                      <span className="mt-0.5 block leading-relaxed text-gray-500">{st("thinkHint")}</span>
                    </span>
                  </label>
                )}

          {noVision && (
            <div className="flex items-start gap-1.5 rounded-lg border border-amber-700/60 bg-amber-900/20 px-2 py-1.5 text-xs text-amber-200">
              <AlertCircle size={14} className="mt-0.5 shrink-0" />
              {st("visionWarn")}
            </div>
          )}

          <button
            onClick={onGenerate}
            disabled={s.busy || !s.images.length}
            title={!s.images.length ? st("noImages") : ""}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-ink-700 disabled:text-gray-500"
          >
            {s.busy ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Wand2 size={16} />
            )}
            {s.busy ? st(s.mode === "panels" ? "generatingPanels" : "generating") : st("generate")}
          </button>

          {s.error && (
            <div className="flex items-start gap-1.5 rounded-lg border border-red-800/60 bg-red-950/40 px-2 py-1.5 text-xs text-red-200">
              <AlertCircle size={14} className="mt-0.5 shrink-0" />
              <span className="break-words">{s.error}</span>
            </div>
          )}
          {/* 後端提醒：例如思考模式沒給出答案、已自動改用不思考 */}
          {(s.notices || []).map((n, i) => (
            <div
              key={i}
              data-testid="notice"
              className="flex items-start gap-1.5 rounded-lg border border-amber-700/60 bg-amber-900/20 px-2 py-1.5 text-xs text-amber-200"
            >
              <AlertCircle size={14} className="mt-0.5 shrink-0" />
              <span className="min-w-0 flex-1 leading-relaxed">{noticeText(n, st)}</span>
              <button
                onClick={() => s.set({ notices: s.notices.filter((_, j) => j !== i) })}
                className="shrink-0 text-amber-400 hover:text-amber-200"
                title="✕"
              >
                ✕
              </button>
            </div>
          ))}
        </aside>

        {/* 結果 */}
        <main className="min-w-0 flex-1 p-3 sm:p-4 lg:overflow-y-auto">
          {!r ? (
            <div className="flex h-full min-h-[40vh] items-center justify-center">
              <p className="max-w-md text-center text-sm leading-relaxed text-gray-500">
                {st("emptyResult")}
              </p>
            </div>
          ) : r.mode === "panels" ? (
            <div className="mx-auto max-w-4xl space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="w-full text-lg font-semibold sm:w-auto sm:min-w-0 sm:flex-1">
                  {r.title || "—"}
                </h2>
                <CopyBtn
                  text={[
                    r.title ? `# ${r.title}` : "",
                    r.premise || "",
                    ...r.panels.map(
                      (p, i) =>
                        `\n[${st("panel", { n: i + 1 })}] ${p.scene || ""}\n` +
                        (p.dialogue || [])
                          .map((d) => (d.speaker ? `${d.speaker}：${d.text}` : d.text))
                          .join("\n") +
                        (p.caption ? `\n（${p.caption}）` : "")
                    ),
                  ]
                    .filter(Boolean)
                    .join("\n")}
                  st={st}
                />
                <button
                  onClick={onGenerate}
                  disabled={s.busy || !s.images.length}
                  className="flex items-center gap-1 rounded-md border border-ink-600 px-2 py-1 text-xs text-gray-300 hover:bg-ink-750 disabled:opacity-50"
                >
                  <RefreshCw size={13} /> {st("regenerate")}
                </button>
                <button
                  onClick={() => toComic(false)}
                  className="flex items-center gap-1 rounded-md bg-indigo-600 px-2 py-1 text-xs text-white hover:bg-indigo-500"
                >
                  <LayoutGrid size={13} /> {st("openInComicImages")}
                </button>
              </div>
              {r.premise && (
                <p className="rounded-xl border border-ink-700 bg-ink-850 p-3 text-sm">
                  <span className="mr-1.5 text-xs font-medium text-gray-500">
                    {st("premise")}
                  </span>
                  {r.premise}
                </p>
              )}
              <div className="space-y-2">
                {r.panels.map((p, i) => (
                  <div
                    key={i}
                    className="flex gap-3 rounded-lg border border-ink-700 bg-ink-850 p-2.5 text-sm"
                  >
                    {p.image_url && (
                      <img
                        src={p.image_url}
                        alt=""
                        className="h-24 w-24 shrink-0 rounded-md object-cover sm:h-32 sm:w-32"
                      />
                    )}
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="font-semibold text-gray-200">
                        {st("panel", { n: i + 1 })}
                      </div>
                      {p.scene && (
                        <p className="text-gray-400">
                          <span className="mr-1 text-xs text-gray-500">{st("panelScene")}</span>
                          {p.scene}
                        </p>
                      )}
                      {p.dialogue?.length > 0 && (
                        <ul className="space-y-0.5">
                          {p.dialogue.map((d, j) => (
                            <li key={j} className="text-gray-100">
                              {d.speaker && (
                                <span className="mr-1 text-gray-400">{d.speaker}：</span>
                              )}
                              {d.text}
                            </li>
                          ))}
                        </ul>
                      )}
                      {p.caption && (
                        <p className="text-xs italic text-gray-400">
                          {st("caption")}：{p.caption}
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : r.mode === "story" ? (
            <article className="mx-auto max-w-3xl space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="w-full text-lg font-semibold sm:w-auto sm:min-w-0 sm:flex-1">{r.title || "—"}</h2>
                <CopyBtn text={`${r.title ? `# ${r.title}\n\n` : ""}${r.story}`} st={st} />
                <button
                  onClick={onGenerate}
                  disabled={s.busy || !s.images.length}
                  className="flex items-center gap-1 rounded-md border border-ink-600 px-2 py-1 text-xs text-gray-300 hover:bg-ink-750 disabled:opacity-50"
                >
                  <RefreshCw size={13} /> {st("regenerate")}
                </button>
                <button
                  onClick={() => toComic(false)}
                  className="flex items-center gap-1 rounded-md bg-indigo-600 px-2 py-1 text-xs text-white hover:bg-indigo-500"
                >
                  <BookOpen size={13} /> {st("sendToComic")}
                </button>
              </div>
              <div className="markdown rounded-xl border border-ink-700 bg-ink-850 p-4 text-[15px] leading-7">
                <Markdown remarkPlugins={[remarkGfm]}>{r.story}</Markdown>
              </div>
            </article>
          ) : (
            <div className="mx-auto max-w-4xl space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="w-full text-lg font-semibold sm:w-auto sm:min-w-0 sm:flex-1">{r.title || "—"}</h2>
                <button
                  onClick={onGenerate}
                  disabled={s.busy || !s.images.length}
                  className="flex items-center gap-1 rounded-md border border-ink-600 px-2 py-1 text-xs text-gray-300 hover:bg-ink-750 disabled:opacity-50"
                >
                  <RefreshCw size={13} /> {st("regenerate")}
                </button>
                <button
                  onClick={() => toComic(false)}
                  className="flex items-center gap-1 rounded-md border border-indigo-500/60 px-2 py-1 text-xs text-indigo-200 hover:bg-indigo-600/20"
                >
                  <BookOpen size={13} /> {st("openInComic")}
                </button>
                <button
                  onClick={() => toComic(true)}
                  disabled={!health.a1111}
                  title={!health.a1111 ? st("needA1111") : ""}
                  className="flex items-center gap-1 rounded-md bg-indigo-600 px-2 py-1 text-xs text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-ink-700 disabled:text-gray-500"
                >
                  <Play size={13} /> {st("openAndRender")}
                </button>
              </div>

              {(r.premise || r.style) && (
                <div className="space-y-1.5 rounded-xl border border-ink-700 bg-ink-850 p-3 text-sm">
                  {r.premise && (
                    <p>
                      <span className="mr-1.5 text-xs font-medium text-gray-500">
                        {st("premise")}
                      </span>
                      {r.premise}
                    </p>
                  )}
                  {r.style && (
                    <p className="font-mono text-xs text-gray-400">
                      <span className="mr-1.5 font-sans font-medium text-gray-500">
                        {st("artStyle")}
                      </span>
                      {r.style}
                    </p>
                  )}
                </div>
              )}

              {r.characters?.length > 0 && (
                <section>
                  <h3 className="mb-1.5 text-xs font-medium text-gray-400">{st("cast")}</h3>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {r.characters.map((c, i) => (
                      <div
                        key={i}
                        className="rounded-lg border border-ink-700 bg-ink-850 p-2"
                      >
                        <div className="text-sm font-semibold text-gray-100">{c.name}</div>
                        <div className="mt-0.5 break-words font-mono text-[11px] leading-relaxed text-gray-400">
                          {c.appearance}
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              <section>
                <h3 className="mb-1.5 text-xs font-medium text-gray-400">{st("panels")}</h3>
                <div className="space-y-2">
                  {r.panels.map((p, i) => (
                    <div
                      key={i}
                      className="rounded-lg border border-ink-700 bg-ink-850 p-2.5 text-sm"
                    >
                      <div className="mb-1 flex flex-wrap items-center gap-1.5">
                        <span className="font-semibold text-gray-200">
                          {st("panel", { n: i + 1 })}
                        </span>
                        <span className="rounded-full border border-emerald-700/60 bg-emerald-900/30 px-2 py-0.5 font-mono text-[11px] text-emerald-200">
                          {st("expression")}: {p.expression || st("noExpression")}
                        </span>
                        {(p.characters || []).map((n) => (
                          <span
                            key={n}
                            className="rounded-full border border-ink-600 px-2 py-0.5 text-[11px] text-gray-300"
                          >
                            {n}
                          </span>
                        ))}
                      </div>
                      <p className="break-words font-mono text-[12px] leading-relaxed text-gray-300">
                        {p.prompt}
                      </p>
                      {p.dialogue?.length > 0 && (
                        <ul className="mt-1.5 space-y-0.5">
                          {p.dialogue.map((d, j) => (
                            <li key={j} className="text-gray-100">
                              {d.speaker && (
                                <span className="mr-1 text-gray-400">{d.speaker}：</span>
                              )}
                              {d.text}
                            </li>
                          ))}
                        </ul>
                      )}
                      {p.caption && (
                        <p className="mt-1 text-xs italic text-gray-400">
                          {st("caption")}：{p.caption}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </section>
            </div>
          )}
        </main>
      </div>

      {settingsOpen && <SettingsModal onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}
