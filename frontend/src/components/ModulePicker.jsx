import { useChat } from "../store/chat";
import { useT } from "../i18n";

// 圖片設定的「VAE / 文字編碼器」多選，跟 Forge Neo 上方的「VAE / Text Encoder」一樣：
// 全部不勾＝自動（Anima 帶 qwen_3_06b_base + qwen_image_vae，其他沿用 Forge 目前選的）；
// 有勾就照勾的載入（Anima 沒勾到的那一類後端自動補上）。
// VAE 只能一個：Forge 依序套用，後面的 VAE 會蓋掉前面的，所以勾新的 VAE 會取消原本那個。
// value：模組檔名陣列；清單是 chat store 的 forgeModules（後端 /api/sd-modules 的 [{name, kind}]）。
export default function ModulePicker({ value, onChange, testId, compact = false }) {
  const t = useT();
  const modules = useChat((s) => s.forgeModules);
  const selected = Array.isArray(value) ? value : value ? [value] : [];
  const known = new Map(modules.map((m) => [m.name, m.kind]));
  // 已不在 Forge 清單的（檔案被移走）：照樣列出並勾著，讓使用者看得到、取消得掉
  const kindOf = (n) => known.get(n) || (/vae/i.test(n) ? "vae" : "text_encoder");
  const missing = selected.filter((n) => !known.has(n));

  const toggle = (name) => {
    if (selected.includes(name)) {
      onChange(selected.filter((n) => n !== name));
      return;
    }
    const kept = kindOf(name) === "vae" ? selected.filter((n) => kindOf(n) !== "vae") : selected;
    onChange([...kept, name]);
  };

  const groups = [
    ["vae", t("modulesVae")],
    ["text_encoder", t("modulesTe")],
  ];

  return (
    <div className="space-y-1" data-testid={testId}>
      <span className={compact ? "block text-xs font-medium text-gray-400" : "text-sm text-gray-300"}>
        {t("sdModules")}
      </span>
      <div className="rounded-lg border border-ink-600 bg-ink-800 p-2 text-sm">
        <div className="flex items-center justify-between gap-2 px-1 pb-1">
          <span data-testid={testId && `${testId}-summary`} className="min-w-0 truncate text-gray-300">
            {selected.length ? selected.join(", ") : t("modulesAuto")}
          </span>
          {selected.length > 0 && (
            <button
              type="button"
              onClick={() => onChange([])}
              className="shrink-0 text-xs text-emerald-400 hover:underline"
            >
              {t("modulesClear")}
            </button>
          )}
        </div>
        <div className="max-h-48 overflow-y-auto border-t border-ink-700 pt-1">
          {groups.map(([kind, label]) => {
            const items = [
              ...missing.filter((n) => kindOf(n) === kind).map((name) => ({ name, missing: true })),
              ...modules.filter((m) => m.kind === kind),
            ];
            if (!items.length) return null;
            return (
              <div key={kind} className="mt-1">
                <div className="px-1 text-xs text-gray-500">{label}</div>
                {items.map((m) => (
                  <label
                    key={m.name}
                    className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 hover:bg-ink-750"
                  >
                    <input
                      type="checkbox"
                      checked={selected.includes(m.name)}
                      onChange={() => toggle(m.name)}
                      className="shrink-0 accent-emerald-500"
                    />
                    <span className={`min-w-0 truncate ${m.missing ? "text-amber-300" : "text-gray-200"}`}>
                      {m.name}
                      {m.missing ? ` ${t("modulesMissing")}` : ""}
                    </span>
                  </label>
                ))}
              </div>
            );
          })}
          {!modules.length && !missing.length && (
            <p className="px-1 py-1 text-xs text-gray-500">{t("modulesNone")}</p>
          )}
        </div>
      </div>
      <span className="block text-xs text-gray-500">{compact ? t("modulesHintShort") : t("modulesHint")}</span>
    </div>
  );
}
