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

// secrets：只存在後端的欄位（API key、MCP token），前端只拿得到 <欄位>_set / <欄位>_env
const SERVICES = [
  { key: "ollama", label: "Ollama", defPort: 11434, secrets: [] },
  // A1111：工具一律走 MCP（Forge 的 /mcp 與 Civitai Helper 的 /civitai-helper/mcp），各要一個 token
  {
    key: "a1111",
    label: "A1111",
    defPort: 7860,
    secrets: [
      { field: "mcp_token", label: "mcpTokenLabel", ph: "mcpTokenPh" },
      { field: "ch_mcp_token", label: "chMcpTokenLabel", ph: "chMcpTokenPh" },
    ],
    hint: "mcpHint",
  },
  // Strata：本機 LLM 伺服器（OpenAI 相容）
  { key: "strata", label: "Strata", defPort: 8081, secrets: [{ field: "api_key", label: "apiKeyLabel", ph: "apiKeyPh" }], hint: "apiKeyHint" },
  // sd.cpp / MMD 動畫：只提供 MCP 伺服器（改圖、MMD 動畫技能的工具），token 是各自專案 .env 的 MCP_TOKEN
  { key: "sdcpp", label: "sd.cpp", defPort: 7861, secrets: [{ field: "mcp_token", label: "sdcppTokenLabel", ph: "sdcppTokenPh" }], hint: "sdcppHint" },
  { key: "mmd", label: "MMD", defPort: 5280, secrets: [{ field: "mcp_token", label: "mmdTokenLabel", ph: "mmdTokenPh" }], hint: "mmdHint" },
];
const SECRET_FIELDS = ["api_key", "mcp_token", "ch_mcp_token"];

// 送給後端的來源設定：秘密欄位只有使用者改過（_dirty）才送，空字串＝清除
function payloadFor(cfg) {
  if (!cfg) return undefined;
  const { _dirty = {}, effective_url, ...rest } = cfg;
  const out = {};
  for (const [k, v] of Object.entries(rest)) {
    if (SECRET_FIELDS.includes(k) || k.endsWith("_set") || k.endsWith("_env")) continue;
    out[k] = v;
  }
  for (const k of SECRET_FIELDS) if (_dirty[k]) out[k] = cfg[k] || "";
  return out;
}

export default function SourcesPanel() {
  const t = useT();
  const loadResources = useChat((s) => s.loadResources);
  const [src, setSrc] = useState(null); // {ollama:{...}, a1111:{...}, ...}
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
          ? {
              state: "ok",
              ms: res.latency_ms,
              model: res.model,
              context: res.context,
              tools: res.tools,
              ch: res.civitai_helper,
            }
          : { state: "fail", detail: res.detail },
      }));
    } catch (e) {
      setTest((r) => ({ ...r, [svc]: { state: "fail", detail: e.message } }));
    }
  };

  const onSave = async () => {
    setSaving(true);
    try {
      await saveSources(Object.fromEntries(SERVICES.map((s) => [s.key, payloadFor(src[s.key])])));
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

      {svc.secrets.map((sec) => (
        <SecretField key={sec.field} cfg={cfg} sec={sec} onPatch={onPatch} />
      ))}
      {svc.hint && <p className="text-[11px] text-gray-500">{t(svc.hint)}</p>}

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
            {test.tools != null && <span className="text-gray-400">· {t("mcpToolsOk", { n: test.tools })}</span>}
            {test.ch?.ok && <span className="text-gray-400">· {t("chToolsOk", { n: test.ch.tools })}</span>}
          </span>
        )}
        {test?.state === "ok" && test.ch && !test.ch.ok && (
          <span className="flex min-w-0 items-center gap-1 text-xs text-amber-300" title={test.ch.detail}>
            <AlertTriangle size={13} className="shrink-0" />
            <span className="truncate">{t("chFailed")} · {test.ch.detail}</span>
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

// 只存在後端的欄位：留空＝保持原值，按「清除」＝儲存時清掉；有環境變數時註明
function SecretField({ cfg, sec, onPatch }) {
  const t = useT();
  const { field } = sec;
  const isSet = cfg[`${field}_set`];
  const fromEnv = cfg[`${field}_env`];
  const dirty = cfg._dirty?.[field];
  const set = (value) => onPatch({ [field]: value, _dirty: { ...(cfg._dirty || {}), [field]: true } });
  return (
    <div className="space-y-1">
      <div className="flex gap-2">
        <input
          type="password"
          value={cfg[field] || ""}
          onChange={(e) => set(e.target.value)}
          placeholder={isSet ? t("apiKeySetPh") : fromEnv ? t("tokenEnvPh") : t(sec.ph)}
          autoComplete="new-password"
          spellCheck={false}
          title={t(sec.label)}
          data-testid={`secret-${field}`}
          className="flex-1 rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 font-mono text-xs outline-none focus:border-ink-500"
        />
        {isSet && (
          <button onClick={() => set("")} className="shrink-0 rounded-lg border border-ink-600 px-2.5 text-xs hover:bg-ink-750">
            {t(field === "api_key" ? "apiKeyClear" : "tokenClear")}
          </button>
        )}
      </div>
      <p className="text-[11px] text-gray-500">
        {t(sec.label)}
        {dirty && !cfg[field] && isSet && <span className="text-amber-400/90"> · {t("tokenWillClear")}</span>}
      </p>
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
