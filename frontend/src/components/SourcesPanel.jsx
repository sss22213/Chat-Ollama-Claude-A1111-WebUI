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
  // Strata：本機 LLM 伺服器（OpenAI 相容）；API key 只存在後端
  { key: "strata", label: "Strata", defPort: 8081, apiKey: true },
];

// 送給後端的來源設定：API key 只有使用者改過（_keyDirty）才送，空字串＝清除
function payloadFor(cfg) {
  if (!cfg) return undefined;
  const { api_key, _keyDirty, api_key_set, effective_url, ...rest } = cfg;
  return _keyDirty ? { ...rest, api_key: api_key || "" } : rest;
}

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
      const res = await testSource({ service: svc, ...payloadFor(src[svc]) });
      setTest((r) => ({
        ...r,
        [svc]: res.ok
          ? { state: "ok", ms: res.latency_ms, model: res.model, context: res.context }
          : { state: "fail", detail: res.detail },
      }));
    } catch (e) {
      setTest((r) => ({ ...r, [svc]: { state: "fail", detail: e.message } }));
    }
  };

  const onSave = async () => {
    setSaving(true);
    try {
      await saveSources({
        ollama: payloadFor(src.ollama),
        a1111: payloadFor(src.a1111),
        strata: payloadFor(src.strata),
      });
      setSrc(await fetchSources()); // 更新「API key 已設定」並清掉輸入框
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

      {SERVICES.filter((s) => src[s.key]).map((s) => (
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

      {svc.apiKey && (
        <div className="space-y-1">
          <div className="flex gap-2">
            <input
              type="password"
              value={cfg.api_key || ""}
              onChange={(e) => onPatch({ api_key: e.target.value, _keyDirty: true })}
              placeholder={cfg.api_key_set ? t("apiKeySetPh") : t("apiKeyPh")}
              autoComplete="new-password"
              spellCheck={false}
              title={t("apiKeyLabel")}
              data-testid={`apikey-${svc.key}`}
              className="flex-1 rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 font-mono text-xs outline-none focus:border-ink-500"
            />
            {cfg.api_key_set && (
              <button
                onClick={() => onPatch({ api_key: "", _keyDirty: true })}
                className="shrink-0 rounded-lg border border-ink-600 px-2.5 text-xs hover:bg-ink-750"
              >
                {t("apiKeyClear")}
              </button>
            )}
          </div>
          <p className="text-[11px] text-gray-500">
            {cfg._keyDirty && !cfg.api_key && cfg.api_key_set ? (
              <span className="text-amber-400/90">{t("apiKeyWillClear")}</span>
            ) : (
              t("apiKeyHint")
            )}
          </p>
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
          <span className="flex min-w-0 items-center gap-1 text-xs text-emerald-400">
            <Check size={13} /> {t("connectedMs", { ms: test.ms })}
            {test.model && (
              <span className="truncate text-gray-400" title={test.model}>
                · {test.model}
                {test.context ? ` · ${Number(test.context).toLocaleString()} ctx` : ""}
              </span>
            )}
          </span>
        )}
        {test?.state === "fail" && (
          <span
            className="flex min-w-0 items-center gap-1 text-xs text-red-300"
            title={test.detail}
            data-testid={`test-fail-${svc.key}`}
          >
            <AlertTriangle size={13} className="shrink-0" /> {t("failed")}
            {test.detail && <span className="truncate text-red-300/80">· {test.detail}</span>}
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
