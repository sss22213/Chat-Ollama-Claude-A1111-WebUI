import { useState } from "react";
import {
  Wand2,
  Loader2,
  Images,
  Plus,
  Trash2,
  AlertCircle,
  ChevronRight,
  ChevronDown,
} from "lucide-react";
import { useComic } from "../store/comic";
import { useChat } from "../store/chat";
import { useCT } from "./comicI18n";
import { fetchComicSystemDefault } from "../lib/comicApi";
import CharacterCast from "./CharacterCast";

function Labeled({ label, children }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-gray-400">{label}</span>
      {children}
    </label>
  );
}

const inputCls =
  "w-full rounded-md border border-ink-600 bg-ink-800 px-2 py-1.5 text-sm outline-none focus:border-ink-500";

export default function ScriptPanel() {
  const ct = useCT();
  const c = useComic();
  const samplers = useChat((s) => s.samplers);
  const sdModels = useChat((s) => s.sdModels);
  const health = useChat((s) => s.health);
  const engine = useChat((s) => s.settings.engine);
  const lang = useChat((s) => s.settings.lang);
  const numCtx = useChat((s) => s.settings.numCtx);
  const chatModel = useChat((s) => s.settings.chatModel);
  const currentConv = useChat((s) => s.currentConversation());
  const [err, setErr] = useState("");
  const [showSysTpl, setShowSysTpl] = useState(false);
  const [loadingDefault, setLoadingDefault] = useState(false);

  const model = currentConv?.model || chatModel;
  const s = c.settings;

  const loadDefaultSystem = async () => {
    setLoadingDefault(true);
    try {
      c.set({ systemBase: await fetchComicSystemDefault() });
    } catch {
      /* 取不到就維持原樣 */
    } finally {
      setLoadingDefault(false);
    }
  };

  const doStoryboard = async () => {
    setErr("");
    if (!c.premise.trim()) {
      setErr(ct("needPremise"));
      return;
    }
    try {
      await c.generateStoryboard({ engine, model, lang, numCtx });
    } catch (e) {
      setErr(e.message || ct("storyboardFailed"));
    }
  };

  return (
    <div className="space-y-4 p-3">
      {/* 標題 + 劇情 */}
      <div className="space-y-2">
        <Labeled label={ct("pageTitle")}>
          <input
            value={c.title}
            onChange={(e) => c.set({ title: e.target.value })}
            placeholder={ct("pageTitlePh")}
            className={inputCls}
          />
        </Labeled>
        <Labeled label={ct("premise")}>
          <textarea
            value={c.premise}
            onChange={(e) => c.set({ premise: e.target.value })}
            placeholder={ct("premisePh")}
            rows={4}
            className={`${inputCls} resize-y`}
          />
        </Labeled>
        <Labeled label={ct("systemPrompt")}>
          <textarea
            value={c.systemPrompt}
            onChange={(e) => c.set({ systemPrompt: e.target.value })}
            placeholder={ct("systemPromptPh")}
            rows={2}
            className={`${inputCls} resize-y`}
          />
        </Labeled>

        {/* 進階：可編輯的 system 範本（覆寫內建） */}
        <div className="rounded-md border border-ink-700">
          <button
            onClick={() => setShowSysTpl((v) => !v)}
            className="flex w-full items-center gap-1.5 px-2 py-1.5 text-xs text-gray-300"
          >
            {showSysTpl ? (
              <ChevronDown size={14} />
            ) : (
              <ChevronRight size={14} />
            )}
            <span className="flex-1 text-left">{ct("systemTemplate")}</span>
            <span
              className={`text-[10px] ${
                c.systemBase.trim() ? "text-amber-300" : "text-gray-500"
              }`}
            >
              {c.systemBase.trim() ? ct("usingCustom") : ct("usingDefault")}
            </span>
          </button>
          {showSysTpl && (
            <div className="space-y-1.5 border-t border-ink-700 p-2">
              <div className="flex gap-1.5">
                <button
                  onClick={loadDefaultSystem}
                  disabled={loadingDefault}
                  className="flex items-center gap-1 rounded-md border border-ink-600 px-2 py-1 text-[11px] text-gray-300 hover:bg-ink-750 disabled:opacity-50"
                >
                  {loadingDefault && (
                    <Loader2 size={12} className="animate-spin" />
                  )}
                  {ct("loadDefault")}
                </button>
                <button
                  onClick={() => c.set({ systemBase: "" })}
                  disabled={!c.systemBase.trim()}
                  className="rounded-md border border-ink-600 px-2 py-1 text-[11px] text-gray-300 hover:bg-ink-750 disabled:opacity-40"
                >
                  {ct("resetDefault")}
                </button>
              </div>
              <textarea
                value={c.systemBase}
                onChange={(e) => c.set({ systemBase: e.target.value })}
                placeholder={ct("loadDefault") + " →"}
                rows={8}
                className={`${inputCls} resize-y font-mono text-[11px] leading-relaxed`}
              />
              <p className="text-[10px] leading-snug text-gray-500">
                {ct("systemTemplateHint")}
              </p>
            </div>
          )}
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Labeled label={ct("panelCount")}>
            <input
              type="number"
              min={1}
              max={16}
              value={c.panelCount}
              onChange={(e) =>
                c.set({
                  panelCount: Math.max(1, Math.min(16, Number(e.target.value) || 1)),
                })
              }
              className={inputCls}
            />
          </Labeled>
          <Labeled label={ct("columns")}>
            <input
              type="number"
              min={1}
              max={5}
              value={c.layout.columns}
              onChange={(e) =>
                c.setLayout({
                  columns: Math.max(1, Math.min(5, Number(e.target.value) || 1)),
                })
              }
              className={inputCls}
            />
          </Labeled>
        </div>
      </div>

      <button
        onClick={doStoryboard}
        disabled={c.storyboarding || !c.premise.trim()}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-ink-700 disabled:text-gray-500"
      >
        {c.storyboarding ? (
          <>
            <Loader2 size={16} className="animate-spin" /> {ct("storyboarding")}
          </>
        ) : (
          <>
            <Wand2 size={16} /> {ct("genStoryboard")} · {engine}
          </>
        )}
      </button>
      {err && (
        <div className="flex items-start gap-1.5 rounded-md bg-red-950/50 px-2 py-1.5 text-xs text-red-300">
          <AlertCircle size={14} className="mt-0.5 shrink-0" />
          <span>{err}</span>
        </div>
      )}

      {/* 角色卡 */}
      <section>
        <h3 className="mb-1 text-sm font-semibold text-gray-200">{ct("cast")}</h3>
        <p className="mb-2 text-[11px] leading-snug text-gray-500">{ct("castHint")}</p>
        <CharacterCast />
      </section>

      {/* 畫風 / negative */}
      <section className="space-y-2">
        <Labeled label={ct("artStyle")}>
          <textarea
            value={c.style}
            onChange={(e) => c.set({ style: e.target.value })}
            placeholder={ct("artStylePh")}
            rows={3}
            className={`${inputCls} min-h-[4.5rem] resize-y font-mono text-xs leading-relaxed`}
          />
        </Labeled>
        <Labeled label={ct("negativePrompt")}>
          <textarea
            value={c.negative}
            onChange={(e) => c.set({ negative: e.target.value })}
            placeholder={ct("negativePh")}
            rows={3}
            className={`${inputCls} min-h-[4.5rem] resize-y font-mono text-xs leading-relaxed`}
          />
        </Labeled>
      </section>

      {/* 出圖設定 */}
      <section className="space-y-2">
        <h3 className="text-sm font-semibold text-gray-200">{ct("imageSettings")}</h3>
        <Labeled label={ct("sdCheckpoint")}>
          <select
            value={s.sd_model_checkpoint}
            onChange={(e) => c.setSettings({ sd_model_checkpoint: e.target.value })}
            className={inputCls}
          >
            <option value="">{ct("useCurrentA1111")}</option>
            {s.sd_model_checkpoint &&
              !sdModels.some((m) => m.model_name === s.sd_model_checkpoint) && (
                <option value={s.sd_model_checkpoint}>
                  {s.sd_model_checkpoint}
                </option>
              )}
            {sdModels.map((m) => (
              <option key={m.model_name} value={m.model_name}>
                {m.model_name}
              </option>
            ))}
          </select>
        </Labeled>
        <div className="grid grid-cols-2 gap-2">
          <Labeled label={ct("width")}>
            <input
              type="number"
              step={64}
              value={s.width}
              onChange={(e) => c.setSettings({ width: Number(e.target.value) || 0 })}
              className={inputCls}
            />
          </Labeled>
          <Labeled label={ct("height")}>
            <input
              type="number"
              step={64}
              value={s.height}
              onChange={(e) => c.setSettings({ height: Number(e.target.value) || 0 })}
              className={inputCls}
            />
          </Labeled>
          <Labeled label={ct("steps")}>
            <input
              type="number"
              value={s.steps}
              onChange={(e) => c.setSettings({ steps: Number(e.target.value) || 0 })}
              className={inputCls}
            />
          </Labeled>
          <Labeled label={ct("cfg")}>
            <input
              type="number"
              step={0.5}
              value={s.cfg_scale}
              onChange={(e) =>
                c.setSettings({ cfg_scale: Number(e.target.value) || 0 })
              }
              className={inputCls}
            />
          </Labeled>
        </div>
        <Labeled label={ct("sampler")}>
          <select
            value={s.sampler_name}
            onChange={(e) => c.setSettings({ sampler_name: e.target.value })}
            className={inputCls}
          >
            {!samplers.includes(s.sampler_name) && (
              <option value={s.sampler_name}>{s.sampler_name}</option>
            )}
            {samplers.map((sm) => (
              <option key={sm} value={sm}>
                {sm}
              </option>
            ))}
          </select>
        </Labeled>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-gray-300">
            <input
              type="checkbox"
              checked={s.lockSeed}
              onChange={(e) => c.setSettings({ lockSeed: e.target.checked })}
              className="accent-emerald-500"
            />
            {ct("lockSeed")}
          </label>
          <input
            type="number"
            value={s.seed}
            disabled={!s.lockSeed}
            onChange={(e) => c.setSettings({ seed: Number(e.target.value) })}
            title={ct("seed")}
            className={`${inputCls} flex-1 disabled:opacity-50`}
          />
        </div>
      </section>

      {/* 動作 */}
      <section className="space-y-2 border-t border-ink-700 pt-3">
        {!health.a1111 && (
          <div className="flex items-center gap-1.5 text-xs text-amber-400">
            <AlertCircle size={14} /> {ct("a1111Offline")}
          </div>
        )}
        <button
          onClick={c.generateAll}
          disabled={!c.panels.length || !!c.genProgress || !health.a1111}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-600 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-ink-700 disabled:text-gray-500"
        >
          {c.genProgress ? (
            <>
              <Loader2 size={16} className="animate-spin" />
              {ct("panelsDone", {
                done: c.genProgress.done,
                total: c.genProgress.total,
              })}
            </>
          ) : (
            <>
              <Images size={16} /> {ct("genAll")}
            </>
          )}
        </button>
        <div className="flex gap-2">
          <button
            onClick={c.addPanel}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-ink-600 py-1.5 text-xs text-gray-300 hover:bg-ink-750"
          >
            <Plus size={14} /> {ct("addPanel")}
          </button>
          <button
            onClick={() => {
              if (window.confirm(ct("confirmReset"))) c.reset();
            }}
            className="flex items-center justify-center gap-1.5 rounded-lg border border-ink-600 px-3 py-1.5 text-xs text-gray-400 hover:bg-ink-750 hover:text-red-400"
          >
            <Trash2 size={14} /> {ct("reset")}
          </button>
        </div>
      </section>
    </div>
  );
}
