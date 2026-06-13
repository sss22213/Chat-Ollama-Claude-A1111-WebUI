import { useEffect, useState } from "react";
import { Plug, Loader2, Check, AlertTriangle, Boxes } from "lucide-react";
import { useChat } from "../store/chat";
import { useT } from "../i18n";
import {
  fetchSources,
  saveSources,
  testSource,
  listDockerContainers,
} from "../lib/api";

const SERVICES = [
  { key: "ollama", label: "Ollama", defPort: 11434 },
  { key: "a1111", label: "A1111", defPort: 7860 },
];

export default function SourcesPanel() {
  const t = useT();
  const loadResources = useChat((s) => s.loadResources);
  const [src, setSrc] = useState(null); // {ollama:{...}, a1111:{...}}
  const [docker, setDocker] = useState(null); // {available, containers, reason}
  const [test, setTest] = useState({}); // {svc: {state, ms, detail}}
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetchSources()
      .then(setSrc)
      .catch(() => {});
  }, []);

  const patch = (svc, p) => {
    setSrc((s) => ({ ...s, [svc]: { ...s[svc], ...p } }));
    setSaved(false);
  };

  const onListContainers = async () => {
    setDocker({ loading: true });
    setDocker(await listDockerContainers());
  };

  const onTest = async (svc) => {
    setTest((r) => ({ ...r, [svc]: { state: "testing" } }));
    try {
      const res = await testSource({ service: svc, ...src[svc] });
      setTest((r) => ({
        ...r,
        [svc]: res.ok
          ? { state: "ok", ms: res.latency_ms }
          : { state: "fail", detail: res.detail },
      }));
    } catch (e) {
      setTest((r) => ({ ...r, [svc]: { state: "fail", detail: e.message } }));
    }
  };

  const onSave = async () => {
    setSaving(true);
    try {
      await saveSources({ ollama: src.ollama, a1111: src.a1111 });
      setSaved(true);
      await loadResources(); // 用新來源重新抓模型/健康狀態
    } catch {
      /* 顯示在各服務測試結果即可 */
    } finally {
      setSaving(false);
    }
  };

  if (!src) return null;

  return (
    <div className="space-y-4">
      <p className="text-xs text-gray-500">{t("sourcesHint")}</p>

      {SERVICES.map((s) => (
        <ServiceBlock
          key={s.key}
          svc={s}
          cfg={src[s.key]}
          test={test[s.key]}
          docker={docker}
          onPatch={(p) => patch(s.key, p)}
          onTest={() => onTest(s.key)}
          onListContainers={onListContainers}
        />
      ))}

      <div className="flex items-center justify-end gap-2">
        {saved && (
          <span className="flex items-center gap-1 text-xs text-emerald-400">
            <Check size={14} /> {t("saved")}
          </span>
        )}
        <button
          onClick={onSave}
          disabled={saving}
          className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-60"
        >
          {saving ? (
            <Loader2 size={15} className="animate-spin" />
          ) : (
            <Plug size={15} />
          )}
          {t("save")}
        </button>
      </div>
    </div>
  );
}

function ServiceBlock({ svc, cfg, test, docker, onPatch, onTest, onListContainers }) {
  const t = useT();
  const isDocker = cfg.mode === "docker";

  return (
    <div className="space-y-2.5 rounded-xl border border-ink-700 bg-ink-800/50 p-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-gray-200">{svc.label}</span>
        <div className="flex overflow-hidden rounded-lg border border-ink-600 text-xs">
          <ModeBtn active={!isDocker} onClick={() => onPatch({ mode: "api" })}>
            {t("modeApi")}
          </ModeBtn>
          <ModeBtn active={isDocker} onClick={() => onPatch({ mode: "docker" })}>
            {t("modeDocker")}
          </ModeBtn>
        </div>
      </div>

      {!isDocker ? (
        <input
          value={cfg.url}
          onChange={(e) => onPatch({ url: e.target.value })}
          placeholder={`http://localhost:${svc.defPort}`}
          spellCheck={false}
          className="w-full rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 font-mono text-xs outline-none focus:border-ink-500"
        />
      ) : (
        <div className="space-y-2">
          <div className="flex gap-2">
            <input
              value={cfg.container}
              onChange={(e) => onPatch({ container: e.target.value })}
              placeholder={svc.key}
              spellCheck={false}
              className="flex-1 rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 font-mono text-xs outline-none focus:border-ink-500"
              title={t("containerLabel")}
            />
            <input
              type="number"
              value={cfg.port}
              onChange={(e) => onPatch({ port: Number(e.target.value) })}
              placeholder={String(svc.defPort)}
              className="w-24 rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 text-xs outline-none focus:border-ink-500"
              title={t("portLabel")}
            />
            <button
              onClick={onListContainers}
              title={t("listContainers")}
              className="flex shrink-0 items-center gap-1 rounded-lg border border-ink-600 px-2.5 text-xs hover:bg-ink-750"
            >
              <Boxes size={14} />
            </button>
          </div>

          {docker?.loading && (
            <p className="text-xs text-gray-500">…</p>
          )}
          {docker && !docker.loading && docker.available === false && (
            <p className="text-xs text-amber-400/80">{t("dockerUnavailable")}</p>
          )}
          {docker?.available && (
            <select
              onChange={(e) => {
                const c = docker.containers.find((x) => x.name === e.target.value);
                if (c)
                  onPatch({
                    container: c.name,
                    port: c.ports?.[0]?.private || cfg.port,
                  });
              }}
              defaultValue=""
              className="w-full rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 text-xs outline-none focus:border-ink-500"
            >
              <option value="" disabled>
                {t("pickContainer")}
              </option>
              {docker.containers.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name}
                  {c.ports?.length
                    ? ` (${c.ports.map((p) => p.private).join(",")})`
                    : ""}
                </option>
              ))}
            </select>
          )}
        </div>
      )}

      <div className="flex items-center gap-2">
        <button
          onClick={onTest}
          className="rounded-lg border border-ink-600 px-3 py-1 text-xs hover:bg-ink-750"
        >
          {test?.state === "testing" ? t("testing") : t("testConnection")}
        </button>
        {test?.state === "ok" && (
          <span className="flex items-center gap-1 text-xs text-emerald-400">
            <Check size={13} /> {t("connectedMs", { ms: test.ms })}
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
      </div>
    </div>
  );
}

function ModeBtn({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={`px-2.5 py-1 ${
        active ? "bg-emerald-600 text-white" : "text-gray-400 hover:bg-ink-750"
      }`}
    >
      {children}
    </button>
  );
}
