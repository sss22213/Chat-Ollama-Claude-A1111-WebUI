import { useEffect, useState } from "react";
import { Loader2, Check, AlertTriangle, Globe } from "lucide-react";
import { useT } from "../i18n";
import { fetchWeb, saveWeb, testWeb } from "../lib/api";

export default function WebPanel() {
  const t = useT();
  const [cfg, setCfg] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [test, setTest] = useState(null); // {state, count, detail}

  useEffect(() => {
    fetchWeb().then(setCfg).catch(() => {});
  }, []);

  if (!cfg) return null;
  const patch = (p) => {
    setCfg((c) => ({ ...c, ...p }));
    setSaved(false);
  };

  const onSave = async () => {
    setSaving(true);
    try {
      const next = await saveWeb(cfg);
      setCfg(next);
      setSaved(true);
    } catch (e) {
      setTest({ state: "fail", detail: e.message });
    } finally {
      setSaving(false);
    }
  };

  const onTest = async () => {
    setTest({ state: "testing" });
    const res = await testWeb();
    setTest(
      res.ok
        ? { state: "ok", count: res.count, ms: res.latency_ms }
        : { state: "fail", detail: res.detail }
    );
  };

  return (
    <div className="space-y-3">
      <label className="block space-y-1">
        <span className="text-sm text-gray-300">{t("webProvider")}</span>
        <select
          value={cfg.provider}
          onChange={(e) => patch({ provider: e.target.value })}
          className="w-full rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 text-sm outline-none focus:border-ink-500"
        >
          <option value="duckduckgo">DuckDuckGo</option>
          <option value="searxng">SearXNG</option>
        </select>
      </label>

      {cfg.provider === "searxng" && (
        <label className="block space-y-1">
          <span className="text-sm text-gray-300">{t("searxngUrl")}</span>
          <input
            value={cfg.searxng_url}
            onChange={(e) => patch({ searxng_url: e.target.value })}
            placeholder="http://searxng:8080"
            spellCheck={false}
            className="w-full rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 font-mono text-xs outline-none focus:border-ink-500"
          />
        </label>
      )}

      <label className="block space-y-1">
        <span className="text-sm text-gray-300">{t("maxResults")}</span>
        <input
          type="number"
          value={cfg.max_results}
          onChange={(e) => patch({ max_results: Number(e.target.value) })}
          className="w-full rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 text-sm outline-none focus:border-ink-500"
        />
      </label>

      <div className="flex items-center gap-2">
        <button
          onClick={onTest}
          className="flex items-center gap-1.5 rounded-lg border border-ink-600 px-3 py-1.5 text-sm hover:bg-ink-750"
        >
          <Globe size={14} />
          {test?.state === "testing" ? t("testing") : t("testConnection")}
        </button>
        {test?.state === "ok" && (
          <span className="flex items-center gap-1 text-xs text-emerald-400">
            <Check size={13} /> {t("connectedMs", { ms: test.ms })} · {test.count}
          </span>
        )}
        {test?.state === "fail" && (
          <span
            className="flex items-center gap-1 truncate text-xs text-red-300"
            title={test.detail}
          >
            <AlertTriangle size={13} /> {t("failed")}
          </span>
        )}
        <div className="flex-1" />
        {saved && (
          <span className="flex items-center gap-1 text-xs text-emerald-400">
            <Check size={14} /> {t("saved")}
          </span>
        )}
        <button
          onClick={onSave}
          disabled={saving}
          className="rounded-lg bg-emerald-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-60"
        >
          {saving ? <Loader2 size={15} className="animate-spin" /> : t("save")}
        </button>
      </div>
    </div>
  );
}
