import { useState } from "react";
import {
  ArrowLeft,
  BookOpen,
  LayoutGrid,
  StretchHorizontal,
  Download,
  Loader2,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  History,
  Layers,
} from "lucide-react";
import { useComic } from "../store/comic";
import { useChat } from "../store/chat";
import { useCT } from "./comicI18n";
import { useT } from "../i18n";
import { navigate } from "../Root";
import ScriptPanel from "./ScriptPanel";
import PanelCard from "./PanelCard";
import ComicPage from "./ComicPage";
import SettingsModal from "../components/SettingsModal";
import HistoryModal from "../components/HistoryModal";
import LoraBrowser from "../components/LoraBrowser";
import { exportComicPng } from "./exportComic";

export default function ComicStudio() {
  const ct = useCT();
  const t = useT();
  const view = useComic((s) => s.view);
  const setView = useComic((s) => s.setView);
  const panels = useComic((s) => s.panels);
  const layout = useComic((s) => s.layout);
  const settings = useComic((s) => s.settings);
  const title = useComic((s) => s.title);
  const applyHistorySettings = useComic((s) => s.applyHistorySettings);
  const appendStyle = useComic((s) => s.appendStyle);

  const models = useChat((s) => s.models);
  const engine = useChat((s) => s.settings.engine);
  const engines = useChat((s) => s.engines);
  const setEngine = useChat((s) => s.setEngine);
  const chatModel = useChat((s) => s.settings.chatModel);
  const setSettings = useChat((s) => s.setSettings);
  const health = useChat((s) => s.health);
  const features = useChat((s) => s.features);

  const [exporting, setExporting] = useState(false);
  const [panelOpen, setPanelOpen] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [loraOpen, setLoraOpen] = useState(false);

  const onExport = async () => {
    if (!panels.length || exporting) return;
    setExporting(true);
    try {
      await exportComicPng({ panels, layout, settings, title });
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-ink-900 text-[#ececec]">
      {/* 頂列 */}
      <header className="flex items-center gap-1.5 border-b border-ink-700 bg-ink-850 px-2 py-2 sm:gap-2 sm:px-3">
        <button
          onClick={() => navigate("")}
          title={ct("backToChat")}
          className="flex shrink-0 items-center gap-1.5 rounded-lg p-2 text-gray-400 hover:bg-ink-750"
        >
          <ArrowLeft size={18} />
        </button>
        <h1 className="flex shrink-0 items-center gap-1.5 text-sm font-semibold">
          <BookOpen size={17} />
          <span className="hidden sm:inline">{ct("comicTitle")}</span>
        </h1>

        <button
          onClick={() => setPanelOpen((v) => !v)}
          title={ct("script")}
          className="shrink-0 rounded-lg p-2 text-gray-400 hover:bg-ink-750 lg:hidden"
        >
          {panelOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}
        </button>

        {/* 引擎 + 模型（分鏡用，沿用聊天頁的選擇） */}
        <select
          value={engine}
          onChange={(e) => setEngine(e.target.value)}
          title={ct("engine")}
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
          className="min-w-0 max-w-[28vw] truncate rounded-lg border border-ink-600 bg-ink-800 px-2 py-1.5 text-sm outline-none focus:border-ink-500 sm:max-w-[16rem]"
        >
          {models.length === 0 && <option>{chatModel || "—"}</option>}
          {models.map((m) => (
            <option key={m.name} value={m.name}>
              {m.name}
            </option>
          ))}
        </select>

        <div className="flex-1" />

        {/* Context window 計量（沿用聊天頁的用量；無用量時顯示視窗大小） */}
        <CtxChip onClick={() => setSettingsOpen(true)} />

        {/* 檢視切換 */}
        <div className="flex shrink-0 overflow-hidden rounded-lg border border-ink-600">
          <button
            onClick={() => setView("grid")}
            className={`flex items-center gap-1 px-2 py-1.5 text-xs ${
              view === "grid"
                ? "bg-ink-700 text-white"
                : "text-gray-400 hover:bg-ink-800"
            }`}
            title={ct("gridView")}
          >
            <LayoutGrid size={14} />
            <span className="hidden sm:inline">{ct("gridView")}</span>
          </button>
          <button
            onClick={() => setView("page")}
            className={`flex items-center gap-1 px-2 py-1.5 text-xs ${
              view === "page"
                ? "bg-ink-700 text-white"
                : "text-gray-400 hover:bg-ink-800"
            }`}
            title={ct("pageView")}
          >
            <StretchHorizontal size={14} />
            <span className="hidden sm:inline">{ct("pageView")}</span>
          </button>
        </div>

        <button
          onClick={onExport}
          disabled={!panels.length || exporting}
          className="flex shrink-0 items-center gap-1.5 rounded-lg bg-indigo-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-ink-700 disabled:text-gray-500 sm:px-3"
          title={ct("exportPng")}
        >
          {exporting ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Download size={14} />
          )}
          <span className="hidden md:inline">
            {exporting ? ct("exporting") : ct("exportPng")}
          </span>
        </button>

        <div className="hidden items-center gap-3 text-xs text-gray-400 lg:flex">
          <span className="flex items-center gap-1">
            <span
              className={`h-2 w-2 rounded-full ${
                health.a1111 ? "bg-emerald-400" : "bg-red-500"
              }`}
            />
            A1111
          </span>
        </div>

        {/* LoRA 參考 */}
        <button
          onClick={() => setLoraOpen(true)}
          className="shrink-0 rounded-lg p-2 text-gray-400 hover:bg-ink-750"
          title={t("loraBrowse")}
        >
          <Layers size={18} />
        </button>

        {/* 提示詞歷史參考（有掛載才顯示，與聊天頁一致） */}
        {features?.promptHistory && (
          <button
            onClick={() => setHistoryOpen(true)}
            className="shrink-0 rounded-lg p-2 text-gray-400 hover:bg-ink-750"
            title={t("history")}
          >
            <History size={18} />
          </button>
        )}

        <button
          onClick={() => setSettingsOpen(true)}
          className="shrink-0 rounded-lg p-2 text-gray-400 hover:bg-ink-750"
          title={t("settings")}
        >
          <Settings size={18} />
        </button>
      </header>

      {/* 內容 */}
      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        {panelOpen && (
          <aside className="shrink-0 overflow-y-auto border-b border-ink-700 lg:w-[360px] lg:border-b-0 lg:border-r">
            <ScriptPanel />
          </aside>
        )}

        <main className="min-w-0 flex-1 overflow-y-auto">
          {panels.length === 0 ? (
            <div className="flex h-full items-center justify-center p-8">
              <p className="max-w-md text-center text-sm leading-relaxed text-gray-500">
                {ct("noPanels")}
              </p>
            </div>
          ) : view === "grid" ? (
            <div className="grid grid-cols-1 gap-3 p-3 sm:grid-cols-2 xl:grid-cols-3">
              {panels.map((p, i) => (
                <PanelCard key={p.id} panel={p} index={i} />
              ))}
            </div>
          ) : (
            <ComicPage />
          )}
        </main>
      </div>

      {settingsOpen && <SettingsModal onClose={() => setSettingsOpen(false)} />}

      {/* LoRA 參考：「帶入」改為接到漫畫畫風，隱藏聊天專屬的「直接生成」 */}
      {loraOpen && (
        <LoraBrowser
          onClose={() => setLoraOpen(false)}
          onInsert={(c) => appendStyle(c.prompt || `<lora:${c.name}:1>`)}
          onGenerate={null}
        />
      )}

      {/* 提示詞歷史參考：「套用到設定」改為套到漫畫出圖設定 */}
      {historyOpen && (
        <HistoryModal
          onClose={() => setHistoryOpen(false)}
          onApply={(record) => applyHistorySettings(record)}
          onGenerate={null}
        />
      )}
    </div>
  );
}

// Context window：有聊天用量就顯示用量/上限的計量條；否則顯示設定的 context 視窗大小。
// 點擊開啟設定（num_ctx 滑桿在裡面）。
function CtxChip({ onClick }) {
  const t = useT();
  const usage = useChat((s) => s.usage);
  const numCtx = useChat((s) => s.settings.numCtx);
  const fmt = (n) =>
    n >= 1000 ? (n / 1000).toFixed(n % 1000 ? 1 : 0) + "k" : String(n);

  if (usage) {
    const total = usage.num_ctx || numCtx;
    const pct = total
      ? Math.min(100, Math.round((usage.prompt_tokens / total) * 100))
      : 0;
    const color =
      pct >= 90 ? "bg-red-500" : pct >= 70 ? "bg-amber-500" : "bg-emerald-500";
    return (
      <button
        onClick={onClick}
        className="hidden shrink-0 items-center gap-1.5 sm:flex"
        title={`${t("contextLabel")}: ${usage.prompt_tokens} / ${total} (${pct}%)`}
      >
        <span className="hidden text-xs text-gray-500 sm:inline">
          {t("contextLabel")}
        </span>
        <div className="h-1.5 w-10 overflow-hidden rounded-full bg-ink-700 sm:w-20">
          <div
            className={`h-full rounded-full ${color}`}
            style={{ width: `${Math.max(pct, 2)}%` }}
          />
        </div>
        <span className="tabular-nums text-xs text-gray-400">
          {fmt(usage.prompt_tokens)}/{fmt(total)}
        </span>
      </button>
    );
  }

  return (
    <button
      onClick={onClick}
      className="hidden shrink-0 items-center gap-1.5 rounded-lg border border-ink-600 px-2 py-1.5 text-xs text-gray-400 hover:bg-ink-750 sm:flex"
      title={t("numCtx")}
    >
      <span className="text-gray-500">{t("contextLabel")}</span>
      <span className="tabular-nums text-gray-300">{fmt(numCtx)}</span>
    </button>
  );
}
