import { useEffect, useState } from "react";
import { X, FolderOpen, HardDrive, Loader2, AlertTriangle } from "lucide-react";
import { useChat } from "../store/chat";
import { useT, LANGS } from "../i18n";
import { fetchStorage, setStorage as apiSetStorage } from "../lib/api";
import DirectoryPicker from "./DirectoryPicker";
import SourcesPanel from "./SourcesPanel";
import WebPanel from "./WebPanel";

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

  // 圖片儲存位置（伺服器端設定）
  const [storage, setStorageState] = useState(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [storageErr, setStorageErr] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchStorage()
      .then(setStorageState)
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

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-2 sm:p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[92vh] w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-ink-700 bg-ink-850 sm:max-h-[85vh]"
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
            <Field label={t("systemPrompt")}>
              <textarea
                value={settings.systemPrompt}
                onChange={(e) => setSettings({ systemPrompt: e.target.value })}
                rows={3}
                placeholder={t("systemPromptPh")}
                className="w-full resize-none rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 text-sm outline-none focus:border-ink-500"
              />
            </Field>
            <Toggle
              label={t("showThinking")}
              checked={settings.think}
              onChange={(v) => setSettings({ think: v })}
              hint={t("showThinkingHint")}
            />
            {settings.engine !== "claude_cli" && (
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
