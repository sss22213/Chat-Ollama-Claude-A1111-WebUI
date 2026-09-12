import {
  Settings,
  PanelLeftOpen,
  Wand2,
  Globe,
  Combine,
  Loader2,
  History,
  Layers,
  BookOpen,
  Sparkles,
  Images,
} from "lucide-react";
import { useChat } from "../store/chat";
import { useT } from "../i18n";

export default function TopBar({
  onToggleSidebar,
  onOpenSettings,
  onOpenHistory,
  onOpenLoras,
  onOpenComic,
  onOpenStory,
  onOpenSkills,
}) {
  const t = useT();
  const models = useChat((s) => s.models);
  const settings = useChat((s) => s.settings);
  const setSettings = useChat((s) => s.setSettings);
  const engines = useChat((s) => s.engines);
  const features = useChat((s) => s.features);
  const skills = useChat((s) => s.skills);
  const setEngine = useChat((s) => s.setEngine);
  const health = useChat((s) => s.health);
  const usage = useChat((s) => s.usage);
  const compact = useChat((s) => s.compact);
  const compacting = useChat((s) => s.compacting);
  const currentConversation = useChat((s) => s.currentConversation());

  // 對話沿用自己的 model；變更時同步到對話與全域預設。
  // 若對話的 model 不在目前引擎的清單中（例如切換引擎後），退回全域預設。
  const rawModel = currentConversation?.model || settings.chatModel;
  const activeModel = models.some((m) => m.name === rawModel)
    ? rawModel
    : settings.chatModel;
  const activeModelMeta = models.find((m) => m.name === activeModel);
  const toolsAvailable = !!activeModelMeta?.supports_tools;
  const skillOn = !!settings.skill;
  const skillLabel =
    settings.skill === "__auto__"
      ? t("skillAuto")
      : skills.find((s) => s.slug === settings.skill)?.name;

  const onChangeModel = (name) => {
    setSettings({ chatModel: name });
    if (currentConversation) {
      // 直接改對話的模型
      useChat.setState((st) => ({
        conversations: st.conversations.map((c) =>
          c.id === st.currentId ? { ...c, model: name } : c
        ),
      }));
    }
  };

  return (
    <header className="flex flex-wrap items-center gap-x-1.5 gap-y-1 border-b border-ink-700 bg-ink-850 px-2 py-1.5 md:flex-nowrap md:gap-3 md:px-3 md:py-2">
      {/* 第一列（手機）／左半（桌面）：側欄、引擎、模型。手機時設定鈕也放這列右端，確保永遠點得到 */}
      <div className="flex min-w-0 basis-full items-center gap-1.5 md:min-w-min md:basis-auto md:gap-3">
      <button
        onClick={onToggleSidebar}
        className="shrink-0 rounded-lg p-2 text-gray-400 hover:bg-ink-750"
        title={t("sidebar")}
      >
        <PanelLeftOpen size={18} />
      </button>

      {/* AI 引擎選擇 */}
      <select
        value={settings.engine}
        onChange={(e) => setEngine(e.target.value)}
        title={t("engine")}
        className="max-w-[7.5rem] shrink-0 rounded-lg border border-ink-600 bg-ink-800 px-2 py-1.5 text-sm outline-none focus:border-ink-500 md:max-w-none"
      >
        <option value="ollama">Ollama</option>
        <option value="claude_cli" disabled={!engines.claude_cli}>
          {engines.claude_cli ? "Claude CLI" : `Claude CLI · ${t("engineUnavailable")}`}
        </option>
        <option value="codex" disabled={!engines.codex}>
          {engines.codex ? "Codex CLI" : `Codex CLI · ${t("engineUnavailable")}`}
        </option>
      </select>

      {/* 模型選擇 */}
      <div className="relative min-w-0 flex-1 md:min-w-[9rem] md:flex-initial">
        <select
          value={activeModel}
          onChange={(e) => onChangeModel(e.target.value)}
          className="w-full truncate rounded-lg border border-ink-600 bg-ink-800 px-2 py-1.5 text-sm outline-none focus:border-ink-500 md:max-w-[20rem] md:px-3"
        >
          {models.length === 0 && <option>{t("modelLoading")}</option>}
          {models.map((m) => (
            <option key={m.name} value={m.name}>
              {(m.supports_tools ? "🔧" : "") +
                (m.supports_vision ? "👁" : "") +
                (m.supports_tools || m.supports_vision ? " " : "")}
              {m.name}
              {/* 後端給的顯示名稱（例如 Claude 別名 opus → Opus 5）；與 name 相同時不重複 */}
              {m.label && m.label.toLowerCase() !== m.name.toLowerCase()
                ? ` · ${m.label}`
                : ""}
            </option>
          ))}
        </select>
      </div>

      <button
        onClick={onOpenSettings}
        className="shrink-0 rounded-lg p-2 text-gray-400 hover:bg-ink-750 md:hidden"
        title={t("settings")}
      >
        <Settings size={18} />
      </button>
      </div>

      {/* 第二列（手機，可橫向捲動）／右半（桌面）：工具與功能。寬度不夠時捲動而不是被裁掉 */}
      <div className="scrollbar-none flex min-w-0 basis-full items-center gap-1.5 overflow-x-auto md:basis-auto md:grow md:gap-3">
      {/* 圖片工具開關（小螢幕只顯示圖示） */}
      <button
        onClick={() => setSettings({ toolsEnabled: !settings.toolsEnabled })}
        disabled={!toolsAvailable}
        title={toolsAvailable ? t("imageToolOn") : t("imageToolUnavailable")}
        className={`flex shrink-0 items-center gap-1.5 rounded-lg border px-2 py-1.5 text-sm transition sm:px-3 ${
          !toolsAvailable
            ? "cursor-not-allowed border-ink-700 text-gray-600"
            : settings.toolsEnabled
            ? "border-emerald-600/50 bg-emerald-600/15 text-emerald-300"
            : "border-ink-600 text-gray-400 hover:bg-ink-750"
        }`}
      >
        <Wand2 size={15} />
        <span className="hidden lg:inline">
          {t("imageTool")}{" "}
          {settings.toolsEnabled && toolsAvailable ? t("on") : t("off")}
        </span>
      </button>

      {/* Web 搜尋開關（小螢幕只顯示圖示） */}
      <button
        onClick={() => setSettings({ webEnabled: !settings.webEnabled })}
        disabled={!toolsAvailable}
        title={toolsAvailable ? t("webToolOn") : t("imageToolUnavailable")}
        className={`flex shrink-0 items-center gap-1.5 rounded-lg border px-2 py-1.5 text-sm transition sm:px-3 ${
          !toolsAvailable
            ? "cursor-not-allowed border-ink-700 text-gray-600"
            : settings.webEnabled
            ? "border-sky-600/50 bg-sky-600/15 text-sky-300"
            : "border-ink-600 text-gray-400 hover:bg-ink-750"
        }`}
      >
        <Globe size={15} />
        <span className="hidden lg:inline">
          {t("webTool")}{" "}
          {settings.webEnabled && toolsAvailable ? t("on") : t("off")}
        </span>
      </button>

      <div className="flex-1" />

      {/* Context 用量 + 壓縮 */}
      {usage && (
        <ContextMeter
          used={usage.prompt_tokens}
          total={usage.num_ctx || settings.numCtx}
        />
      )}
      {(currentConversation?.messages?.length || 0) >= 3 && (
        <button
          onClick={compact}
          disabled={compacting}
          title={t("compactHint")}
          className="flex shrink-0 items-center gap-1.5 rounded-lg border border-ink-600 px-2.5 py-1.5 text-xs text-gray-300 hover:bg-ink-750 disabled:opacity-60"
        >
          {compacting ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Combine size={14} />
          )}
          <span className="hidden lg:inline">
            {compacting ? t("compacting") : t("compact")}
          </span>
        </button>
      )}

      {/* 服務狀態 */}
      <div className="hidden items-center gap-3 text-xs text-gray-400 lg:flex">
        <StatusDot ok={health.ollama} label="Ollama" />
        <StatusDot ok={health.a1111} label="A1111" />
      </div>

      {/* 技能（Agent Skills）：啟用時高亮並顯示名稱 */}
      <button
        onClick={onOpenSkills}
        title={skillLabel || t("skills")}
        className={`flex shrink-0 items-center gap-1.5 rounded-lg border px-2 py-1.5 text-sm transition sm:px-3 ${
          skillOn
            ? "border-violet-600/50 bg-violet-600/15 text-violet-300"
            : "border-ink-600 text-gray-300 hover:bg-ink-750"
        }`}
      >
        <Sparkles size={15} />
        <span className="hidden max-w-[8rem] truncate lg:inline">
          {skillLabel || t("skills")}
        </span>
      </button>

      <button
        onClick={onOpenComic}
        className="flex shrink-0 items-center gap-1.5 rounded-lg border border-ink-600 px-2 py-1.5 text-sm text-gray-300 hover:bg-ink-750 sm:px-3"
        title={t("comicStudio")}
      >
        <BookOpen size={16} />
        <span className="hidden lg:inline">{t("comicStudio")}</span>
      </button>

      <button
        onClick={onOpenStory}
        className="flex shrink-0 items-center gap-1.5 rounded-lg border border-ink-600 px-2 py-1.5 text-sm text-gray-300 hover:bg-ink-750 sm:px-3"
        title={t("storyStudio")}
      >
        <Images size={16} />
        <span className="hidden lg:inline">{t("storyStudio")}</span>
      </button>

      <button
        onClick={onOpenLoras}
        className="shrink-0 rounded-lg p-2 text-gray-400 hover:bg-ink-750"
        title={t("loraBrowse")}
      >
        <Layers size={18} />
      </button>

      {features?.promptHistory && (
        <button
          onClick={onOpenHistory}
          className="shrink-0 rounded-lg p-2 text-gray-400 hover:bg-ink-750"
          title={t("history")}
        >
          <History size={18} />
        </button>
      )}

      <button
        onClick={onOpenSettings}
        className="hidden shrink-0 rounded-lg p-2 text-gray-400 hover:bg-ink-750 md:block"
        title={t("settings")}
      >
        <Settings size={18} />
      </button>
      </div>
    </header>
  );
}

function ContextMeter({ used, total }) {
  const t = useT();
  const pct = total ? Math.min(100, Math.round((used / total) * 100)) : 0;
  const color =
    pct >= 90 ? "bg-red-500" : pct >= 70 ? "bg-amber-500" : "bg-emerald-500";
  const fmt = (n) => (n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n));
  return (
    <div
      className="flex shrink-0 items-center gap-1.5 sm:gap-2"
      title={`${t("contextLabel")}: ${used} / ${total} (${pct}%)`}
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
        {fmt(used)}/{fmt(total)}
      </span>
    </div>
  );
}

function StatusDot({ ok, label }) {
  return (
    <span className="flex items-center gap-1">
      <span
        className={`h-2 w-2 rounded-full ${
          ok ? "bg-emerald-400" : "bg-red-500"
        }`}
      />
      {label}
    </span>
  );
}
