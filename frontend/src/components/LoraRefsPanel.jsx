import { useCallback, useEffect, useState } from "react";
import { Loader2, Unlink, Check, X } from "lucide-react";
import { fetchLoraReferences, replaceLoraReferences } from "../lib/api";
import { useComic } from "../store/comic";

/**
 * 「檢查失效引用」：漫畫作品裡用到、但目前沒有的 LoRA 名稱（LoRA 改名或刪除後），
 * 每個名稱可以選一個現有的 LoRA 替換（有把握的建議預先選好），套用時連開著的作品一起改。
 */
// names：目前所有 LoRA 的名稱（沒有建議時也能自己挑一個）
export default function LoraRefsPanel({ t, onClose, names = [] }) {
  const [state, setState] = useState({ loading: true, items: [], error: "" });
  const [pick, setPick] = useState({}); // 失效名稱 → 要換成的名稱（"" = 不換）
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState("");

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: "" }));
    try {
      const d = await fetchLoraReferences();
      const items = d.missing || [];
      setState({ loading: false, items, error: "" });
      setPick(Object.fromEntries(items.map((it) => [it.name, it.suggestion || ""])));
    } catch (e) {
      setState({ loading: false, items: [], error: e.message });
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  const apply = async () => {
    const mapping = Object.fromEntries(Object.entries(pick).filter(([, v]) => v));
    if (!Object.keys(mapping).length) return;
    setBusy(true);
    try {
      const r = await replaceLoraReferences(mapping);
      useComic.getState().replaceLoraNames(mapping);
      const n = (r.projects || []).reduce((sum, p) => sum + (p.count || 0), 0);
      setDone(t("loraRefsDone", { n, projects: (r.projects || []).length }));
      await load();
    } catch (e) {
      setState((s) => ({ ...s, error: e.message }));
    } finally {
      setBusy(false);
    }
  };

  const chosen = Object.values(pick).filter(Boolean).length;
  return (
    <div data-testid="lora-refs" className="mb-4 rounded-xl border border-ink-600 bg-ink-850 p-3 text-sm">
      <div className="mb-2 flex items-center gap-2">
        <Unlink size={15} className="text-amber-300" />
        <span className="font-medium text-gray-200">{t("loraRefsTitle")}</span>
        <span className="min-w-0 flex-1 truncate text-xs text-gray-500">{t("loraRefsHint")}</span>
        <button onClick={onClose} className="rounded p-1 text-gray-500 hover:bg-ink-750 hover:text-gray-300">
          <X size={14} />
        </button>
      </div>
      {state.loading ? (
        <div className="flex items-center gap-2 py-2 text-xs text-gray-400">
          <Loader2 size={13} className="animate-spin" /> {t("loading")}
        </div>
      ) : state.error ? (
        <p className="text-xs text-red-300">{state.error}</p>
      ) : !state.items.length ? (
        <p className="flex items-center gap-1.5 text-xs text-emerald-300" data-testid="lora-refs-ok">
          <Check size={13} /> {done || t("loraRefsNone")}
        </p>
      ) : (
        <>
          <div className="space-y-1.5">
            {state.items.map((it) => (
              <div key={it.name} data-testid="lora-refs-item" className="flex flex-wrap items-center gap-2 rounded-lg bg-ink-900 px-2 py-1.5">
                <code className="text-xs text-red-300">{`<lora:${it.name}>`}</code>
                <span className="min-w-0 flex-1 truncate text-[11px] text-gray-500" title={it.projects.map((p) => p.title || p.id).join(", ")}>
                  {t("loraRefsUsedIn", { n: it.projects.length })}: {it.projects.map((p) => p.title || p.id).join(", ")}
                </span>
                <span className="text-xs text-gray-500">→</span>
                <input
                  value={pick[it.name] || ""}
                  onChange={(e) => setPick((p) => ({ ...p, [it.name]: e.target.value.trim() }))}
                  list={`lora-refs-${it.name}`}
                  placeholder={t("loraRefsKeep")}
                  data-testid="lora-refs-pick"
                  className="w-56 max-w-[45%] rounded border border-ink-600 bg-ink-800 px-1.5 py-0.5 font-mono text-xs outline-none focus:border-ink-500"
                />
                <datalist id={`lora-refs-${it.name}`}>
                  {[...new Set([...it.candidates, ...names])].map((c) => (
                    <option key={c} value={c} />
                  ))}
                </datalist>
              </div>
            ))}
          </div>
          <div className="mt-2 flex items-center gap-2">
            {done && <span className="text-xs text-emerald-300">{done}</span>}
            <div className="flex-1" />
            <button
              onClick={apply}
              disabled={busy || !chosen}
              data-testid="lora-refs-apply"
              className="flex items-center gap-1 rounded-lg bg-emerald-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
            >
              {busy ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
              {t("loraRefsApply", { n: chosen })}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
