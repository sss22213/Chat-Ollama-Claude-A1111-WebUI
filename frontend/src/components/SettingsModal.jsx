import { useEffect, useRef, useState } from "react";
import { X, FolderOpen, HardDrive, Loader2, AlertTriangle, Pencil } from "lucide-react";
import { useChat, normEffort } from "../store/chat";
import { useT, LANGS } from "../i18n";
import {
  fetchStorage,
  setStorage as apiSetStorage,
  fetchPromptHistoryDir,
  fetchSkillsDir,
  saveSkillsDir,
  saveSkillScripts,
  saveSkillMaxChars,
} from "../lib/api";
import DirectoryPicker from "./DirectoryPicker";
import SourcesPanel from "./SourcesPanel";
import WebPanel from "./WebPanel";
import ModulePicker from "./ModulePicker";

// 各引擎可用的推理強度（統一在設定裡呈現，不需切換引擎即可分別調整）
// ollama 的 effort 僅 gpt-oss 會用到（其他模型用上方 think 開關）
// codex / claude 的 options 是「模型能力未知時」的後備；目前引擎是它們時會改用
// 所選模型宣告的 efforts（GPT-6 / 6.1 / 5.6 系列多了 max/ultra；Opus 4.6 / Sonnet 4.6 沒有 xhigh、
// Haiku 4.5（完整 ID claude-haiku-4-5；haiku 別名已是 Haiku 5.5）不支援）
const EFFORT_ENGINES = [
  { key: "claude_cli", label: "Claude", options: ["low", "medium", "high", "xhigh", "max"] },
  { key: "codex", label: "Codex", options: ["low", "medium", "high", "xhigh"] },
  // Strata：reasoning_effort；none＝不思考直接回答（「顯示思考」關掉時也會送 none）
  { key: "strata", label: "Strata", options: ["none", "low", "medium", "high"] },
  { key: "ollama", label: "Ollama · gpt-oss", options: ["low", "medium", "high"] },
];

export default function SettingsModal({ onClose }) {
  const t = useT();
  const settings = useChat((s) => s.settings);
  const setSettings = useChat((s) => s.setSettings);
  const setImageSettings = useChat((s) => s.setImageSettings);
  const sdModels = useChat((s) => s.sdModels);
  const samplers = useChat((s) => s.samplers);
  const models = useChat((s) => s.models);
  const img = settings.imageSettings;
  const modelMaxCtx = models.find((m) => m.name === settings.chatModel)
    ?.context_length;
  // 各引擎獨立的 effort：一次顯示全部，寫回時只改該引擎的鍵
  const eff = normEffort(settings.effort);
  const setEffortFor = (key, v) =>
    setSettings({ effort: { ...normEffort(settings.effort), [key]: v } });
  // codex / claude：所選模型宣告的推理強度（models 只載目前引擎的清單，故只有目前引擎可得）
  const modelEfforts = ["codex", "claude_cli", "strata"].includes(settings.engine)
    ? models.find((m) => m.name === settings.chatModel)?.efforts
    : null;
  const effortOptionsFor = (key, fallback) =>
    key === settings.engine && modelEfforts ? modelEfforts : fallback;

  // 圖片儲存位置（伺服器端設定）
  const [storage, setStorageState] = useState(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [storageErr, setStorageErr] = useState("");
  const [saving, setSaving] = useState(false);

  // 系統提示的獨立編輯視窗
  const [promptOpen, setPromptOpen] = useState(false);

  // 提示詞歷史目錄（env 預設、UI 可覆寫）
  const setPromptHistoryDir = useChat((s) => s.setPromptHistoryDir);
  const [histDir, setHistDir] = useState(null);
  const [histPickerOpen, setHistPickerOpen] = useState(false);
  const [histErr, setHistErr] = useState("");
  const [histSaving, setHistSaving] = useState(false);

  // 技能目錄（env 預設、UI 可覆寫）
  const reloadSkills = useChat((s) => s.reloadSkills);
  const [skillsDir, setSkillsDir] = useState(null);
  const [skillsPickerOpen, setSkillsPickerOpen] = useState(false);
  const [skillsErr, setSkillsErr] = useState("");
  const [skillsSaving, setSkillsSaving] = useState(false);

  useEffect(() => {
    fetchStorage()
      .then(setStorageState)
      .catch(() => {});
    fetchPromptHistoryDir()
      .then(setHistDir)
      .catch(() => {});
    fetchSkillsDir()
      .then(setSkillsDir)
      .catch(() => {});
  }, []);

  const onPickDir = async (path) => {
    setSaving(true);
    setStorageErr("");
    try {
      const info = await apiSetStorage(path);
      setStorageState(info);
      setPickerOpen(false);
    } catch (e) {
      setStorageErr(e.message);
    } finally {
      setSaving(false);
    }
  };

  const onSetHistDir = async (dir) => {
    setHistSaving(true);
    setHistErr("");
    try {
      const info = await setPromptHistoryDir(dir);
      setHistDir(info);
      setHistPickerOpen(false);
    } catch (e) {
      setHistErr(e.message);
    } finally {
      setHistSaving(false);
    }
  };

  // 技能提示詞長度上限：輸入框自己的草稿值，失焦或按 Enter 才存（避免每打一個字就存）
  const [maxCharsDraft, setMaxCharsDraft] = useState(null);
  const onSaveSkillMaxChars = async () => {
    if (maxCharsDraft === null) return;
    setSkillsErr("");
    try {
      const info = await saveSkillMaxChars(Math.max(0, Math.round(Number(maxCharsDraft) || 0)));
      setSkillsDir(info);
      setMaxCharsDraft(null);
    } catch (e) {
      setSkillsErr(e.message);
    }
  };

  const onSetSkillScripts = async (enabled) => {
    setSkillsErr("");
    try {
      const info = await saveSkillScripts(enabled);
      setSkillsDir(info);
      await reloadSkills(); // 工具清單（run_skill_script）跟著變
    } catch (e) {
      setSkillsErr(e.message);
    }
  };

  const onSetSkillsDir = async (dir) => {
    setSkillsSaving(true);
    setSkillsErr("");
    try {
      const info = await saveSkillsDir(dir);
      setSkillsDir(info);
      setSkillsPickerOpen(false);
      await reloadSkills(); // 目錄變了，重抓技能清單
    } catch (e) {
      setSkillsErr(e.message);
    } finally {
      setSkillsSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-2 sm:p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[92dvh] w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-ink-700 bg-ink-850 sm:max-h-[85dvh]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-ink-700 px-5 py-3">
          <h2 className="text-base font-semibold">{t("settings")}</h2>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-gray-400 hover:bg-ink-750"
          >
            <X size={18} />
          </button>
        </div>

        <div className="space-y-6 overflow-y-auto px-5 py-4">
          {/* 一般 */}
          <Section title={t("general")}>
            <Field label={t("language")}>
              <select
                value={settings.lang}
                onChange={(e) => setSettings({ lang: e.target.value })}
                className="w-full rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 text-sm outline-none focus:border-ink-500"
              >
                {LANGS.map((l) => (
                  <option key={l.code} value={l.code}>
                    {l.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("sendKey")}>
              <select
                value={settings.sendKey === "shiftEnter" ? "shiftEnter" : "enter"}
                onChange={(e) => setSettings({ sendKey: e.target.value })}
                data-testid="send-key"
                className="w-full rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 text-sm outline-none focus:border-ink-500"
              >
                <option value="enter">{t("sendKeyEnter")}</option>
                <option value="shiftEnter">{t("sendKeyShiftEnter")}</option>
              </select>
              <p className="text-xs text-gray-500">{t("sendKeyHint")}</p>
            </Field>
            {/* 系統提示：這裡只顯示前兩行和字數，按下去在獨立的大視窗裡編輯（設定頁的小框寫長提示不好改） */}
            <div className="space-y-1">
              <span className="text-sm text-gray-300">{t("systemPrompt")}</span>
              <div className="flex items-stretch gap-2">
                <button
                  type="button"
                  onClick={() => setPromptOpen(true)}
                  data-testid="system-prompt-preview"
                  className="min-w-0 flex-1 rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 text-left text-sm hover:border-ink-500"
                >
                  {settings.systemPrompt?.trim() ? (
                    <span className="line-clamp-2 whitespace-pre-wrap break-words text-gray-200">
                      {settings.systemPrompt}
                    </span>
                  ) : (
                    <span className="text-gray-500">{t("systemPromptEmpty")}</span>
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => setPromptOpen(true)}
                  data-testid="system-prompt-edit"
                  className="flex shrink-0 items-center gap-1.5 rounded-lg border border-ink-600 px-3 py-2 text-sm hover:bg-ink-750"
                >
                  <Pencil size={15} />
                  {t("systemPromptEdit")}
                </button>
              </div>
              {settings.systemPrompt ? (
                <p className="text-xs text-gray-500">
                  {t("systemPromptChars", { n: settings.systemPrompt.length })}
                </p>
              ) : null}
            </div>
            <Toggle
              label={t("showThinking")}
              checked={settings.think}
              onChange={(v) => setSettings({ think: v })}
              hint={t("showThinkingHint")}
            />
            <Toggle
              label={t("sendGenInfo")}
              checked={settings.sendGenInfo !== false}
              onChange={(v) => setSettings({ sendGenInfo: v })}
              hint={t("sendGenInfoHint")}
            />
            <Toggle
              label={t("autoCompact")}
              checked={!!settings.autoCompact}
              onChange={(v) => setSettings({ autoCompact: v })}
              hint={t("autoCompactHint")}
            />
            {settings.autoCompact && (
              <div className="flex items-center gap-3">
                <span className="w-32 shrink-0 text-sm text-gray-300">
                  {t("autoCompactAt")}
                </span>
                <select
                  value={String(settings.autoCompactAt || 0.8)}
                  onChange={(e) => setSettings({ autoCompactAt: Number(e.target.value) })}
                  className="flex-1 rounded-lg border border-ink-600 bg-ink-800 px-3 py-1.5 text-sm outline-none focus:border-ink-500"
                >
                  {["0.6", "0.7", "0.8", "0.9"].map((v) => (
                    <option key={v} value={v}>
                      {Math.round(Number(v) * 100)}%
                    </option>
                  ))}
                </select>
              </div>
            )}
            <Field label={t("effortLabel")}>
              <div className="space-y-2">
                {EFFORT_ENGINES.map(({ key, label, options }) => {
                  const opts = effortOptionsFor(key, options);
                  return (
                    <div key={key} className="flex items-center gap-3">
                      <span className="w-32 shrink-0 text-sm text-gray-300">
                        {label}
                      </span>
                      {opts.length === 0 ? (
                        /* 所選模型宣告不支援推理強度（例如 claude-haiku-4-5）：不送 --effort */
                        <select
                          disabled
                          data-testid={`effort-${key}`}
                          className="flex-1 rounded-lg border border-ink-700 bg-ink-850 px-3 py-2 text-sm text-gray-500"
                        >
                          <option>{t("effortNotSupported")}</option>
                        </select>
                      ) : (
                        <select
                          value={opts.includes(eff[key]) ? eff[key] : opts.includes("medium") ? "medium" : opts[0]}
                          onChange={(e) => setEffortFor(key, e.target.value)}
                          data-testid={`effort-${key}`}
                          className="flex-1 rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 text-sm outline-none focus:border-ink-500"
                        >
                          {opts.map((lvl) => (
                            <option key={lvl} value={lvl}>
                              {lvl}
                            </option>
                          ))}
                        </select>
                      )}
                    </div>
                  );
                })}
              </div>
              <p className="text-xs text-gray-500">
                {t("effortHint")} {t("effortHintOss")}
              </p>
            </Field>
            {settings.engine === "ollama" && (
              <Field label={t("numCtx")}>
                <input
                  type="number"
                  step={1024}
                  min={1024}
                  value={settings.numCtx}
                  onChange={(e) =>
                    setSettings({ numCtx: Number(e.target.value) || 1024 })
                  }
                  className="w-full rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 text-sm outline-none focus:border-ink-500"
                />
                <p className="text-xs text-gray-500">
                  {t("numCtxHint", {
                    max: modelMaxCtx ? modelMaxCtx.toLocaleString() : "?",
                  })}
                </p>
              </Field>
            )}
            {/* Strata 的 context 是伺服器啟動時的 --max-context，API 改不了：只顯示，並說去哪改 */}
            {settings.engine === "strata" && (
              <Field label={t("numCtx")}>
                <input
                  type="text"
                  readOnly
                  value={modelMaxCtx ? modelMaxCtx.toLocaleString() : "?"}
                  data-testid="numctx-strata"
                  className="w-full cursor-default rounded-lg border border-ink-700 bg-ink-850 px-3 py-2 text-sm text-gray-400 outline-none"
                />
                <p className="text-xs text-gray-500">{t("numCtxStrataHint")}</p>
              </Field>
            )}
          </Section>

          {/* 服務來源 */}
          <Section title={t("sourcesSection")}>
            <SourcesPanel />
          </Section>

          {/* Web 搜尋 */}
          <Section title={t("webSection")}>
            <WebPanel />
          </Section>

          {/* 圖片儲存位置 */}
          <Section title={t("storageSection")}>
            <Field label={t("storageLabel")}>
              <div className="flex items-center gap-2">
                <div className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-ink-600 bg-ink-800 px-3 py-2">
                  <HardDrive size={15} className="shrink-0 text-gray-400" />
                  <span className="truncate font-mono text-xs text-gray-200">
                    {storage?.image_dir || t("loading")}
                  </span>
                </div>
                <button
                  onClick={() => setPickerOpen(true)}
                  className="flex shrink-0 items-center gap-1.5 rounded-lg border border-ink-600 px-3 py-2 text-sm hover:bg-ink-750"
                >
                  {saving ? (
                    <Loader2 size={15} className="animate-spin" />
                  ) : (
                    <FolderOpen size={15} />
                  )}
                  {t("chooseFolder")}
                </button>
              </div>
            </Field>
            {storage && (
              <p className="text-xs text-gray-500">
                {t("storageCount", { count: storage.count })} ·{" "}
                {storage.writable ? t("writable") : t("notWritable")}
              </p>
            )}
            {storageErr && (
              <p className="flex items-center gap-1.5 text-xs text-red-300">
                <AlertTriangle size={13} /> {storageErr}
              </p>
            )}
          </Section>

          {/* 提示詞歷史目錄 */}
          <Section title={t("history")}>
            <Field label={t("historyDirLabel")}>
              <div className="flex items-center gap-2">
                <div className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-ink-600 bg-ink-800 px-3 py-2">
                  <HardDrive size={15} className="shrink-0 text-gray-400" />
                  <span className="truncate font-mono text-xs text-gray-200">
                    {histDir?.dir || t("historyDirUnset")}
                  </span>
                </div>
                <button
                  onClick={() => setHistPickerOpen(true)}
                  className="flex shrink-0 items-center gap-1.5 rounded-lg border border-ink-600 px-3 py-2 text-sm hover:bg-ink-750"
                >
                  {histSaving ? (
                    <Loader2 size={15} className="animate-spin" />
                  ) : (
                    <FolderOpen size={15} />
                  )}
                  {t("chooseFolder")}
                </button>
              </div>
            </Field>
            {histDir && (
              <p className="text-xs">
                {histDir.available ? (
                  <span className="text-emerald-400">
                    {t("historyFound", { count: histDir.count ?? "?" })}
                  </span>
                ) : (
                  <span className="text-amber-300/90">{t("historyNotFound")}</span>
                )}
                {histDir.override ? (
                  <button
                    onClick={() => onSetHistDir("")}
                    className="ml-2 text-gray-400 underline hover:text-gray-200"
                  >
                    {t("historyDirReset")}
                  </button>
                ) : null}
              </p>
            )}
            <p className="text-xs text-gray-500">{t("historyDirHint")}</p>
            {histErr && (
              <p className="flex items-center gap-1.5 text-xs text-red-300">
                <AlertTriangle size={13} /> {histErr}
              </p>
            )}
          </Section>

          {/* 技能目錄 */}
          <Section title={t("skillsSection")}>
            <Field label={t("skillsDirLabel")}>
              <div className="flex items-center gap-2">
                <div className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-ink-600 bg-ink-800 px-3 py-2">
                  <HardDrive size={15} className="shrink-0 text-gray-400" />
                  <span className="truncate font-mono text-xs text-gray-200">
                    {skillsDir?.dir || t("loading")}
                  </span>
                </div>
                <button
                  onClick={() => setSkillsPickerOpen(true)}
                  className="flex shrink-0 items-center gap-1.5 rounded-lg border border-ink-600 px-3 py-2 text-sm hover:bg-ink-750"
                >
                  {skillsSaving ? (
                    <Loader2 size={15} className="animate-spin" />
                  ) : (
                    <FolderOpen size={15} />
                  )}
                  {t("chooseFolder")}
                </button>
              </div>
            </Field>
            {skillsDir && (
              <p className="text-xs">
                <span className="text-emerald-400">
                  {t("skillsFound", { count: skillsDir.count ?? 0 })}
                </span>
                {" · "}
                {skillsDir.writable ? (
                  <span className="text-gray-500">{t("writable")}</span>
                ) : (
                  <span className="text-amber-300/90">{t("notWritable")}</span>
                )}
                {skillsDir.override ? (
                  <button
                    onClick={() => onSetSkillsDir("")}
                    className="ml-2 text-gray-400 underline hover:text-gray-200"
                  >
                    {t("historyDirReset")}
                  </button>
                ) : null}
              </p>
            )}
            <p className="text-xs text-gray-500">{t("skillsDirHint")}</p>
            <div className="space-y-1 rounded-lg border border-ink-700 p-3">
              <label className="flex items-center justify-between gap-3">
                <span className="text-sm text-gray-300">{t("skillMaxCharsLabel")}</span>
                <input
                  data-testid="skill-max-chars"
                  type="number"
                  min={0}
                  step={1000}
                  value={maxCharsDraft ?? skillsDir?.max_chars ?? 0}
                  onChange={(e) => setMaxCharsDraft(e.target.value)}
                  onBlur={onSaveSkillMaxChars}
                  onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
                  className="w-28 rounded-lg border border-ink-600 bg-ink-800 px-2 py-1.5 text-right text-sm outline-none focus:border-ink-500"
                />
              </label>
              <p data-testid="skill-max-chars-state" className="text-xs text-gray-500">
                {(skillsDir?.max_chars || 0) > 0
                  ? t("skillMaxCharsLimited", { n: skillsDir.max_chars })
                  : t("skillMaxCharsUnlimited")}
                {" "}
                {t("skillMaxCharsHint")}
              </p>
            </div>
            <div data-testid="skill-scripts" className="rounded-lg border border-ink-700 p-3">
              <Toggle
                label={t("skillScriptsLabel")}
                checked={!!skillsDir?.scripts_enabled}
                onChange={onSetSkillScripts}
                hint={t("skillScriptsHint")}
              />
            </div>
            {skillsErr && (
              <p className="flex items-center gap-1.5 text-xs text-red-300">
                <AlertTriangle size={13} /> {skillsErr}
              </p>
            )}
          </Section>

          {/* 圖片生成參數 */}
          <Section title={t("sdSection")}>
            <Field label={t("sdCheckpoint")}>
              <select
                value={img.sd_model_checkpoint}
                onChange={(e) =>
                  setImageSettings({ sd_model_checkpoint: e.target.value })
                }
                className="w-full rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 text-sm outline-none focus:border-ink-500"
              >
                <option value="">{t("useCurrentA1111")}</option>
                {sdModels.map((m) => (
                  <option key={m.model_name} value={m.model_name}>
                    {m.model_name}
                  </option>
                ))}
              </select>
            </Field>

            <ModulePicker
              testId="sd-modules"
              value={img.sd_modules}
              onChange={(v) => setImageSettings({ sd_modules: v })}
            />

            <Field label={t("sampler")}>
              <select
                value={img.sampler_name}
                onChange={(e) =>
                  setImageSettings({ sampler_name: e.target.value })
                }
                className="w-full rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 text-sm outline-none focus:border-ink-500"
              >
                {samplers.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </Field>

            <div className="grid grid-cols-2 gap-3">
              <Num label={t("width")} value={img.width} step={64} onChange={(v) => setImageSettings({ width: v })} />
              <Num label={t("height")} value={img.height} step={64} onChange={(v) => setImageSettings({ height: v })} />
              <Num label={t("steps")} value={img.steps} onChange={(v) => setImageSettings({ steps: v })} />
              <Num label={t("cfg")} value={img.cfg_scale} step={0.5} onChange={(v) => setImageSettings({ cfg_scale: v })} />
              <Num label={t("seed")} value={img.seed} onChange={(v) => setImageSettings({ seed: v })} />
              <Num label={t("denoise")} value={img.denoising_strength} step={0.05} onChange={(v) => setImageSettings({ denoising_strength: v })} />
            </div>

            <Field label={t("defaultNegative")}>
              <textarea
                value={img.negative_prompt}
                onChange={(e) =>
                  setImageSettings({ negative_prompt: e.target.value })
                }
                rows={2}
                placeholder="lowres, bad anatomy, worst quality, ..."
                className="w-full resize-none rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 text-sm outline-none focus:border-ink-500"
              />
            </Field>
          </Section>
        </div>

        <div className="border-t border-ink-700 px-5 py-3 text-right">
          <button
            onClick={onClose}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500"
          >
            {t("done")}
          </button>
        </div>
      </div>

      {pickerOpen && (
        <div onClick={(e) => e.stopPropagation()}>
          <DirectoryPicker
            initialPath={storage?.image_dir}
            onPick={onPickDir}
            onClose={() => setPickerOpen(false)}
          />
        </div>
      )}

      {histPickerOpen && (
        <div onClick={(e) => e.stopPropagation()}>
          <DirectoryPicker
            initialPath={histDir?.dir || histDir?.default}
            requireWritable={false}
            title={t("pickerTitleHistory")}
            onPick={onSetHistDir}
            onClose={() => setHistPickerOpen(false)}
          />
        </div>
      )}

      {skillsPickerOpen && (
        <div onClick={(e) => e.stopPropagation()}>
          <DirectoryPicker
            initialPath={skillsDir?.dir || skillsDir?.default}
            title={t("pickerTitleSkills")}
            onPick={onSetSkillsDir}
            onClose={() => setSkillsPickerOpen(false)}
          />
        </div>
      )}

      {promptOpen && (
        <div onClick={(e) => e.stopPropagation()}>
          <SystemPromptEditor
            value={settings.systemPrompt || ""}
            onSave={(v) => setSettings({ systemPrompt: v })}
            onClose={() => setPromptOpen(false)}
          />
        </div>
      )}
    </div>
  );
}

// 系統提示的獨立編輯視窗：改的是草稿，按儲存（或 Ctrl / ⌘ + Enter）才寫回設定。
// 有改過時，取消、Esc、點視窗外面都會先確認要不要放棄修改。
function SystemPromptEditor({ value, onSave, onClose }) {
  const t = useT();
  const [draft, setDraft] = useState(value);
  const areaRef = useRef(null);
  const downOnBackdrop = useRef(false);
  const dirty = draft !== value;

  const cancel = () => {
    if (!dirty || window.confirm(t("systemPromptDiscard"))) onClose();
  };
  const save = () => {
    if (dirty) onSave(draft);
    onClose();
  };

  useEffect(() => {
    const onKey = (e) => {
      // 輸入法選字中的 Esc / Enter 是給輸入法的（取消選字），不能關掉視窗
      if (e.isComposing || e.keyCode === 229) return;
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        cancel();
      } else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        e.stopPropagation();
        save();
      }
    };
    window.addEventListener("keydown", onKey, true); // capture：比其他頁面的 Esc 快捷鍵先處理
    return () => window.removeEventListener("keydown", onKey, true);
  });

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-2 sm:p-4"
      // 只有在外面按下、也在外面放開才算點外面（在框裡選字拖到外面放開不算）
      onMouseDown={(e) => (downOnBackdrop.current = e.target === e.currentTarget)}
      onClick={(e) => e.target === e.currentTarget && downOnBackdrop.current && cancel()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="system-prompt-title"
        data-testid="system-prompt-editor"
        className="flex h-[92dvh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-ink-700 bg-ink-850 sm:h-[80dvh]"
      >
        <div className="flex items-center justify-between border-b border-ink-700 px-5 py-3">
          <h2 id="system-prompt-title" className="text-base font-semibold">
            {t("systemPrompt")}
          </h2>
          <button
            type="button"
            onClick={cancel}
            aria-label={t("cancel")}
            className="rounded-lg p-1.5 text-gray-400 hover:bg-ink-750"
          >
            <X size={18} />
          </button>
        </div>

        <div className="flex min-h-0 flex-1 flex-col px-5 py-4">
          <textarea
            ref={areaRef}
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={t("systemPromptPh")}
            data-testid="system-prompt-textarea"
            className="min-h-0 w-full flex-1 resize-none rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 text-sm leading-relaxed outline-none focus:border-ink-500"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2 border-t border-ink-700 px-5 py-3">
          <span className="mr-auto text-xs text-gray-500" data-testid="system-prompt-count">
            {t("systemPromptChars", { n: draft.length })}
            <span className="hidden sm:inline"> · {t("systemPromptKeys")}</span>
          </span>
          <button
            type="button"
            onClick={() => {
              setDraft("");
              areaRef.current?.focus();
            }}
            disabled={!draft}
            className="rounded-lg border border-ink-600 px-3 py-2 text-sm hover:bg-ink-750 disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent"
          >
            {t("systemPromptClear")}
          </button>
          <button
            type="button"
            onClick={cancel}
            className="rounded-lg border border-ink-600 px-3 py-2 text-sm hover:bg-ink-750"
          >
            {t("cancel")}
          </button>
          <button
            type="button"
            onClick={save}
            data-testid="system-prompt-save"
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500"
          >
            {t("save")}
          </button>
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div className="space-y-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
        {title}
      </h3>
      {children}
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label className="block space-y-1">
      <span className="text-sm text-gray-300">{label}</span>
      {children}
    </label>
  );
}

function Num({ label, value, onChange, step = 1 }) {
  return (
    <Field label={label}>
      <input
        type="number"
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 text-sm outline-none focus:border-ink-500"
      />
    </Field>
  );
}

function Toggle({ label, checked, onChange, hint }) {
  return (
    <div className="space-y-1">
      <label className="flex cursor-pointer items-center justify-between">
        <span className="text-sm text-gray-300">{label}</span>
        <button
          type="button"
          onClick={() => onChange(!checked)}
          className={`relative h-6 w-11 rounded-full transition ${
            checked ? "bg-emerald-600" : "bg-ink-600"
          }`}
        >
          <span
            className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition ${
              checked ? "left-[1.375rem]" : "left-0.5"
            }`}
          />
        </button>
      </label>
      {hint && <p className="text-xs text-gray-500">{hint}</p>}
    </div>
  );
}
