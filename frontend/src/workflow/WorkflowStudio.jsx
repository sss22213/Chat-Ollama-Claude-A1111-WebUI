import { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowLeft,
  Brain,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  CopyPlus,
  CornerDownRight,
  Download,
  FileText,
  FolderOpen,
  FolderUp,
  History,
  Loader2,
  Lock,
  MessageSquare,
  Package,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Send,
  Square,
  Trash2,
  Workflow,
  Wrench,
} from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useChat, normEffort, effortKeyFor } from "../store/chat";
import { useWorkflow, inputTemplate } from "../store/workflow";
import { fileToB64, imagesIn, outputText, readWorkflowFile, workflowExportUrl } from "../lib/workflowApi";
import { useWT } from "./workflowI18n";
import GraphDiagram from "./GraphDiagram";
import { navigate } from "../Root";
import { copyText } from "../lib/clipboard";
import DirectoryPicker from "../components/DirectoryPicker";

const inputCls =
  "w-full rounded-md border border-ink-600 bg-ink-800 px-2 py-1.5 text-sm outline-none focus:border-ink-500";
const btnCls =
  "flex items-center justify-center gap-1.5 rounded-md border border-ink-600 px-2.5 py-1.5 text-xs text-gray-200 hover:bg-ink-750 disabled:cursor-not-allowed disabled:opacity-50";
const SKIP_UPLOAD = /(^|\/)(\.venv|venv|node_modules|__pycache__|\.git|\.langgraph_api)(\/|$)/;

const RUN_COLOR = {
  done: "text-emerald-300",
  running: "text-sky-300",
  error: "text-red-300",
  cancelled: "text-gray-400",
  stopped: "text-gray-400",
  interrupted: "text-amber-300",
};

// 時間戳（秒）→ 「3 分鐘前」或日期
function ago(ts, wt) {
  if (!ts) return "";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return wt("justNow");
  if (s < 3600) return wt("minutesAgo", { n: Math.floor(s / 60) });
  if (s < 86400) return wt("hoursAgo", { n: Math.floor(s / 3600) });
  return new Date(ts * 1000).toLocaleDateString();
}

const VENV_COLOR = {
  ready: "bg-emerald-500",
  outdated: "bg-amber-500",
  installing: "bg-sky-500",
  missing: "bg-gray-500",
};

export default function WorkflowStudio() {
  const wt = useWT();
  const w = useWorkflow();
  const loaded = useWorkflow((s) => s.loaded);
  const load = useWorkflow((s) => s.load);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-ink-900 text-[#ececec]">
      <Header />
      {loaded && !w.enabled && <EnableBanner />}
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <aside className="max-h-[40vh] shrink-0 overflow-y-auto border-b border-ink-700 p-3 md:max-h-none md:w-72 md:border-b-0 md:border-r">
          <ProjectList />
        </aside>
        <main className="min-h-0 min-w-0 flex-1 overflow-y-auto p-3 sm:p-4">
          {w.error && <ErrorBox text={w.error} />}
          {w.project ? (
            <ProjectView />
          ) : (
            loaded && !w.projects.length && <Help wt={wt} />
          )}
        </main>
      </div>
    </div>
  );
}

function Header() {
  const wt = useWT();
  const engine = useChat((c) => c.settings.engine);
  const engines = useChat((c) => c.engines);
  const setEngine = useChat((c) => c.setEngine);
  const models = useChat((c) => c.models);
  const chatModel = useChat((c) => c.settings.chatModel);
  const setSettings = useChat((c) => c.setSettings);
  return (
    <header className="flex items-center gap-1.5 border-b border-ink-700 bg-ink-850 px-2 py-2 sm:gap-2 sm:px-3">
      <button
        onClick={() => navigate("")}
        title={wt("backToChat")}
        className="shrink-0 rounded-lg p-2 text-gray-400 hover:bg-ink-750"
      >
        <ArrowLeft size={18} />
      </button>
      <h1 className="flex shrink-0 items-center gap-1.5 text-sm font-semibold">
        <Workflow size={17} />
        <span className="hidden sm:inline">{wt("title")}</span>
      </h1>
      {/* 引擎 + 模型（沿用聊天頁的選擇）：工作流裡 webui_app.chat 預設用這個 */}
      <select
        value={engine}
        onChange={(e) => setEngine(e.target.value)}
        title={wt("engine")}
        className="shrink-0 rounded-lg border border-ink-600 bg-ink-800 px-2 py-1.5 text-sm outline-none focus:border-ink-500"
      >
        <option value="ollama">Ollama</option>
        <option value="claude_cli" disabled={!engines.claude_cli}>
          Claude CLI
        </option>
        <option value="codex" disabled={!engines.codex}>
          Codex CLI
        </option>
        <option value="strata" disabled={!engines.strata}>
          Strata
        </option>
      </select>
      <select
        value={chatModel}
        onChange={(e) => setSettings({ chatModel: e.target.value })}
        className="min-w-0 max-w-[34vw] truncate rounded-lg border border-ink-600 bg-ink-800 px-2 py-1.5 text-sm outline-none focus:border-ink-500 sm:max-w-[16rem]"
      >
        {models.length === 0 && <option>{chatModel || "—"}</option>}
        {models.map((m) => (
          <option key={m.name} value={m.name}>
            {(m.supports_vision ? "👁 " : "") + m.name}
          </option>
        ))}
      </select>
    </header>
  );
}

function EnableBanner() {
  const wt = useWT();
  const setEnabled = useWorkflow((s) => s.setEnabled);
  const load = useWorkflow((s) => s.load);
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-amber-700/50 bg-amber-900/20 px-3 py-2 text-xs text-amber-100">
      <Lock size={14} className="shrink-0" />
      <span className="min-w-0 flex-1 leading-relaxed">
        <b>{wt("enableTitle")}</b> — {wt("enableHint")}
      </span>
      <button
        data-testid="wf-enable"
        onClick={async () => {
          await setEnabled(true);
          load();
        }}
        className="shrink-0 rounded-md bg-amber-600 px-2.5 py-1 font-medium text-white hover:bg-amber-500"
      >
        {wt("enableBtn")}
      </button>
    </div>
  );
}

function ErrorBox({ text, trace }) {
  return (
    <div className="mb-3 rounded-md border border-red-800/60 bg-red-950/40 px-3 py-2 text-xs text-red-200">
      <div className="flex items-start gap-1.5">
        <AlertCircle size={14} className="mt-0.5 shrink-0" />
        <span className="min-w-0 whitespace-pre-wrap break-words">{text}</span>
      </div>
      {trace && (
        <details className="mt-1.5">
          <summary className="cursor-pointer text-red-300/80">Traceback</summary>
          <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap text-[11px] text-red-200/80">{trace}</pre>
        </details>
      )}
    </div>
  );
}

function Help({ wt }) {
  return (
    <div className="max-w-2xl rounded-lg border border-ink-700 bg-ink-850 p-3 text-xs leading-relaxed text-gray-400">
      <div className="mb-1 font-medium text-gray-200">{wt("helpTitle")}</div>
      {wt("help")}
    </div>
  );
}

// ---------------- 專案清單 ----------------

function ProjectList() {
  const wt = useWT();
  const w = useWorkflow();
  const [name, setName] = useState("");
  const [template, setTemplate] = useState("example");
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const folderRef = useRef(null);
  const zipRef = useRef(null);

  const doCreate = async () => {
    setErr("");
    setBusy("create");
    try {
      await w.create(name.trim() || (template === "empty" ? "my-graph" : template), template);
      setName("");
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy("");
    }
  };

  const doUpload = async (files, isZip) => {
    if (!files?.length) return;
    setErr("");
    const first = files[0];
    const fromName = isZip
      ? first.name.replace(/\.zip$/i, "")
      : (first.webkitRelativePath || first.name).split("/")[0];
    const slug = (name.trim() || fromName).replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^[-.]+/, "");
    let replace = false;
    if (w.projects.some((p) => p.slug === slug)) {
      if (!window.confirm(wt("replaceConfirm", { name: slug }))) return;
      replace = true;
    }
    setBusy("upload");
    try {
      if (isZip) {
        await w.upload(slug, { zip_b64: await fileToB64(first), replace });
      } else {
        const list = [];
        for (const f of files) {
          const path = f.webkitRelativePath || f.name;
          if (SKIP_UPLOAD.test(path) || /\.pyc$/.test(path)) continue;
          list.push({ path, b64: await fileToB64(f) });
        }
        await w.upload(slug, { files: list, replace });
      }
      setName("");
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy("");
      if (folderRef.current) folderRef.current.value = "";
      if (zipRef.current) zipRef.current.value = "";
    }
  };

  const q = w.query.trim().toLowerCase();
  const shown = q
    ? w.projects.filter((p) =>
        [p.slug, p.description || "", ...(p.graphs || [])].some((x) => x.toLowerCase().includes(q))
      )
    : w.projects;

  return (
    <div className="space-y-3">
      <FolderCard />
      <div>
        <div className="mb-1.5 flex items-center gap-2">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400">{wt("projects")}</h2>
          <span className="text-[10px] text-gray-500">{w.projects.length}</span>
          <div className="flex-1" />
          <button onClick={() => w.load()} title={wt("rescan")} data-testid="wf-rescan" className="text-gray-500 hover:text-gray-200">
            <RefreshCw size={13} />
          </button>
        </div>
        {w.projects.length > 3 && (
          <input
            value={w.query}
            onChange={(e) => w.setQuery(e.target.value)}
            placeholder={wt("searchPh")}
            data-testid="wf-search"
            className={`${inputCls} mb-1.5 text-xs`}
          />
        )}
        {w.projects.length === 0 && w.loaded && (
          <p className="text-[11px] leading-snug text-gray-500">{wt("noProjects")}</p>
        )}
        <ul className="space-y-1">
          {shown.map((p) => (
            <li key={p.slug}>
              <button
                onClick={() => w.select(p.slug)}
                data-testid={`wf-project-${p.slug}`}
                className={`w-full rounded-md px-2 py-1.5 text-left ${
                  p.slug === w.selected ? "bg-ink-700 text-white" : "text-gray-300 hover:bg-ink-800"
                }`}
              >
                <span className="flex items-center gap-2 text-sm">
                  <span
                    className={`h-2 w-2 shrink-0 rounded-full ${VENV_COLOR[p.venv?.state] || "bg-gray-500"}`}
                    title={wt(`venv_${p.venv?.state || "missing"}`)}
                  />
                  <span className="min-w-0 flex-1 truncate">{p.slug}</span>
                  <span className="shrink-0 text-[10px] text-gray-500" title={wt("graphCount")}>
                    {p.error ? "!" : (p.graphs || []).length}
                  </span>
                </span>
                {(p.description || p.last_run) && (
                  <span className="mt-0.5 flex items-center gap-1.5 pl-4 text-[10px] text-gray-500">
                    <span className="min-w-0 flex-1 truncate">{p.description}</span>
                    {p.last_run && (
                      <span className={`shrink-0 ${RUN_COLOR[p.last_run.status] || ""}`} title={`${p.last_run.graph} · ${wt(`status_${p.last_run.status}`)}`}>
                        {ago(p.last_run.started_at, wt)}
                      </span>
                    )}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="space-y-1.5 rounded-lg border border-ink-700 p-2">
        <div className="text-xs font-medium text-gray-300">{wt("newProject")}</div>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={wt("projectName")}
          data-testid="wf-new-name"
          className={inputCls}
        />
        <select value={template} onChange={(e) => setTemplate(e.target.value)} data-testid="wf-template" className={inputCls}>
          {w.templates.map((t) => {
            const key = `template_${t.id}`;
            const label = wt(key);
            return (
              <option key={t.id} value={t.id}>
                {label === key ? t.description || t.id : label}
              </option>
            );
          })}
          <option value="empty">{wt("templateEmpty")}</option>
        </select>
        <button onClick={doCreate} disabled={!!busy} data-testid="wf-create" className={`${btnCls} w-full`}>
          {busy === "create" ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
          {wt("create")}
        </button>
        <div className="pt-1 text-xs font-medium text-gray-300">{wt("uploadProject")}</div>
        <div className="grid grid-cols-2 gap-1.5">
          <button onClick={() => folderRef.current?.click()} disabled={!!busy} className={btnCls}>
            <FolderUp size={13} /> {wt("uploadFolder")}
          </button>
          <button onClick={() => zipRef.current?.click()} disabled={!!busy} className={btnCls}>
            <Package size={13} /> {wt("uploadZip")}
          </button>
        </div>
        <input
          ref={folderRef}
          type="file"
          multiple
          webkitdirectory=""
          className="hidden"
          onChange={(e) => doUpload([...e.target.files], false)}
        />
        <input
          ref={zipRef}
          type="file"
          accept=".zip,application/zip"
          data-testid="wf-upload-zip"
          className="hidden"
          onChange={(e) => doUpload([...e.target.files], true)}
        />
        {busy === "upload" && (
          <div className="flex items-center gap-1 text-[11px] text-gray-400">
            <Loader2 size={12} className="animate-spin" /> {wt("uploading")}
          </div>
        )}
        <p className="text-[10px] leading-snug text-gray-500">{wt("uploadHint")}</p>
        {err && <ErrorBox text={err} />}
      </div>
      {w.enabled && (
        <button onClick={() => w.setEnabled(false)} className="text-[11px] text-gray-500 underline hover:text-gray-300">
          {wt("disableBtn")}
        </button>
      )}
    </div>
  );
}

// ---------------- 專案 ----------------

function NameForm({ initial, label, onSubmit, onCancel }) {
  const wt = useWT();
  const [value, setValue] = useState(initial);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setErr("");
    setBusy(true);
    try {
      await onSubmit(value.trim());
    } catch (e) {
      setErr(e.message);
      setBusy(false);
    }
  };
  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-ink-600 bg-ink-850 p-2">
      <span className="text-xs text-gray-400">{label}</span>
      <input
        autoFocus
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.nativeEvent.isComposing) submit();
          if (e.key === "Escape") onCancel();
        }}
        data-testid="wf-name-input"
        className={`${inputCls} w-56 text-xs`}
      />
      <button onClick={submit} disabled={busy || !value.trim()} data-testid="wf-name-ok" className={btnCls}>
        {busy ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
      </button>
      <button onClick={onCancel} className={btnCls}>✕</button>
      {err && <span className="w-full text-[11px] text-red-300">{err}</span>}
      <span className="w-full text-[10px] text-gray-500">{wt("needsReinstall")}</span>
    </div>
  );
}

function ProjectView() {
  const wt = useWT();
  const w = useWorkflow();
  const [tab, setTab] = useState("run");
  const [naming, setNaming] = useState(null); // null | "rename" | "duplicate"
  const p = w.project;
  const state = p.venv?.state || "missing";

  useEffect(() => {
    setNaming(null);
  }, [p.slug]);
  useEffect(() => {
    if (tab === "history") w.loadRuns();
  }, [tab, p.slug]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (w.installing) setTab("install");
  }, [w.installing]);

  return (
    <div className="mx-auto max-w-5xl space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="min-w-0 truncate text-base font-semibold">{p.slug}</h2>
        <span className="flex items-center gap-1.5 rounded-full border border-ink-600 px-2 py-0.5 text-[11px] text-gray-300">
          <span className={`h-2 w-2 rounded-full ${VENV_COLOR[w.installing ? "installing" : state]}`} />
          <span data-testid="wf-venv">{wt(`venv_${w.installing ? "installing" : state}`)}</span>
          {p.venv?.langgraph && state !== "missing" && (
            <span className="text-gray-500">· langgraph {p.venv.langgraph}</span>
          )}
        </span>
        <div className="flex-1" />
        <button
          onClick={() => w.install()}
          disabled={!w.enabled || w.installing}
          title={!w.enabled ? wt("needEnable") : ""}
          data-testid="wf-install"
          className={btnCls}
        >
          {w.installing ? <Loader2 size={13} className="animate-spin" /> : <Package size={13} />}
          {state === "missing" ? wt("install") : wt("reinstall")}
        </button>
        <button onClick={() => setNaming("rename")} data-testid="wf-rename" className={btnCls} title={wt("rename")}>
          <Pencil size={13} /> <span className="hidden lg:inline">{wt("rename")}</span>
        </button>
        <button onClick={() => setNaming("duplicate")} data-testid="wf-duplicate" className={btnCls} title={wt("duplicate")}>
          <CopyPlus size={13} /> <span className="hidden lg:inline">{wt("duplicate")}</span>
        </button>
        <a href={workflowExportUrl(p.slug)} download={`${p.slug}.zip`} data-testid="wf-export" className={btnCls} title={wt("exportHint")}>
          <Download size={13} /> <span className="hidden lg:inline">{wt("export")}</span>
        </a>
        <button
          onClick={() => window.confirm(wt("deleteConfirm", { name: p.slug })) && w.remove(p.slug)}
          className={`${btnCls} hover:text-red-300`}
          title={wt("deleteProject")}
        >
          <Trash2 size={13} /> <span className="hidden lg:inline">{wt("deleteProject")}</span>
        </button>
      </div>
      {p.description && <p className="-mt-1 text-xs text-gray-400">{p.description}</p>}
      {p.path && (
        <p className="-mt-1 truncate font-mono text-[10px] text-gray-600" title={p.path}>
          {p.path}
        </p>
      )}
      {naming && (
        <NameForm
          key={naming}
          initial={naming === "rename" ? p.slug : `${p.slug}-copy`}
          label={naming === "rename" ? wt("renameTo") : wt("duplicateAs")}
          onCancel={() => setNaming(null)}
          onSubmit={async (name) => {
            if (naming === "rename") await w.rename(name);
            else await w.duplicate(name);
            setNaming(null);
          }}
        />
      )}
      {p.error && <ErrorBox text={wt("configError") + p.error} />}

      <div className="flex gap-1 border-b border-ink-700">
        {[
          ["run", wt("tabRun")],
          ["history", wt("tabHistory")],
          ["files", wt("tabFiles")],
          ["install", wt("tabInstall")],
        ].map(([k, label]) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            data-testid={`wf-tab-${k}`}
            className={`-mb-px border-b-2 px-3 py-1.5 text-sm ${
              tab === k ? "border-indigo-500 text-white" : "border-transparent text-gray-400 hover:text-gray-200"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "run" && <RunPanel />}
      {tab === "history" && <HistoryPanel onReuse={() => setTab("run")} />}
      {tab === "files" && <FilesPanel />}
      {tab === "install" && <InstallPanel />}
    </div>
  );
}

function InstallPanel() {
  const wt = useWT();
  const log = useWorkflow((s) => s.installLog);
  const ref = useRef(null);
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [log]);
  return (
    <pre
      ref={ref}
      data-testid="wf-install-log"
      className="h-[55vh] overflow-auto whitespace-pre-wrap break-words rounded-lg border border-ink-700 bg-ink-900 p-2 font-mono text-[11px] leading-relaxed text-gray-300"
    >
      {log.length === 0 && <span className="text-gray-600">{wt("installLogEmpty")}</span>}
      {log.map((l, i) => (
        <div
          key={i}
          className={l.error ? "text-red-300" : l.done ? "text-emerald-300" : l.text.startsWith("$ ") ? "text-sky-300" : ""}
        >
          {l.text}
        </div>
      ))}
    </pre>
  );
}

// ---------------- 執行 ----------------

function RunPanel() {
  const wt = useWT();
  const w = useWorkflow();
  const settings = useChat((c) => c.settings);
  const models = useChat((c) => c.models);
  const [copied, setCopied] = useState(false);
  const ids = Object.keys(w.project.config?.graphs || {});
  const info = w.graphs?.[w.graph];
  const key = `${w.selected}:${w.graph}`;
  const text = w.inputs[key] ?? "";
  const ready = w.project.venv?.state === "ready" || w.project.venv?.state === "outdated";
  const running = w.run?.status === "running";
  const command = `/workflow ${w.selected}:${w.graph} `;

  const start = () => {
    const engine = settings.engine;
    let effort = normEffort(settings.effort)[effortKeyFor(engine)];
    const supported = models.find((m) => m.name === settings.chatModel)?.efforts;
    if (supported?.length && !supported.includes(effort)) {
      effort = supported.includes("medium") ? "medium" : supported[0];
    }
    w.start({
      engine,
      model: settings.chatModel,
      think: settings.think,
      effort,
      numCtx: settings.numCtx,
      imageSettings: settings.imageSettings,
    });
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1.5 text-xs text-gray-400">
          {wt("graph")}
          <select
            value={w.graph}
            onChange={(e) => w.setGraph(e.target.value)}
            data-testid="wf-graph"
            className="rounded-md border border-ink-600 bg-ink-800 px-2 py-1 text-sm text-gray-100 outline-none"
          >
            {ids.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </select>
        </label>
        <button
          onClick={() => w.inspect()}
          disabled={!w.enabled || !ready || w.inspecting}
          title={!w.enabled ? wt("needEnable") : !ready ? wt("needInstall") : ""}
          data-testid="wf-inspect"
          className={btnCls}
        >
          {w.inspecting ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
          {w.inspecting ? wt("loadingGraph") : wt("loadGraph")}
        </button>
      </div>
      {w.inspectError && <ErrorBox text={w.inspectError} />}
      {info?.error && <ErrorBox text={`${wt("graphError")}: ${info.error}`} trace={info.traceback} />}
      <GraphPanel
        info={info}
        run={w.run?.project === w.selected && w.run?.graph === w.graph ? w.run : null}
      />

      <div className="space-y-1.5">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-gray-400">{wt("input")}</span>
          {info?.input_schema && (
            <button onClick={() => w.setInput(inputTemplate(info.input_schema))} className="text-[11px] text-indigo-300 hover:underline">
              {wt("fillTemplate")}
            </button>
          )}
        </div>
        <textarea
          value={text}
          onChange={(e) => w.setInput(e.target.value)}
          placeholder={wt("inputPh")}
          rows={5}
          data-testid="wf-input"
          className={`${inputCls} resize-y font-mono text-xs`}
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {running ? (
          <button onClick={() => w.stop()} data-testid="wf-stop" className="flex items-center gap-1.5 rounded-lg bg-red-600 px-3 py-1.5 text-sm text-white hover:bg-red-500">
            <Square size={14} /> {wt("stop")}
          </button>
        ) : (
          <button
            onClick={start}
            disabled={!w.enabled || !ready || !w.graph}
            title={!w.enabled ? wt("needEnable") : !ready ? wt("needInstall") : ""}
            data-testid="wf-run"
            className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-ink-700 disabled:text-gray-500"
          >
            <Play size={14} /> {wt("run")} · {settings.engine}
          </button>
        )}
        {running && (
          <span className={`flex items-center gap-1 text-xs ${w.run.waiting ? "text-amber-300" : "text-gray-400"}`}>
            {w.run.waiting ? <MessageSquare size={13} /> : <Loader2 size={13} className="animate-spin" />}
            {w.run.waiting ? wt("waitingInput") : wt("running")}
          </span>
        )}
        <div className="flex-1" />
        <span className="flex min-w-0 items-center gap-1 text-[11px] text-gray-500">
          {wt("chatHint")}
          <code className="truncate rounded bg-ink-800 px-1 py-0.5 text-gray-300">{command}…</code>
          <button
            onClick={async () => {
              if (await copyText(command)) {
                setCopied(true);
                setTimeout(() => setCopied(false), 1200);
              }
            }}
            className="shrink-0 text-gray-400 hover:text-gray-200"
          >
            {copied ? <Check size={12} /> : <Copy size={12} />}
          </button>
        </span>
      </div>

      {running && w.run.waiting && (
        <InterruptForm
          key={w.run.waiting.id || w.run.events.length}
          waiting={w.run.waiting}
          busy={!!w.run.answering}
          error={w.run.answerError}
          onSubmit={(value) => w.answer(value)}
        />
      )}
      {w.run && <RunView run={w.run} />}
    </div>
  );
}

const optionList = (opts) =>
  (opts || []).map((o) => (o && typeof o === "object" ? { value: o.value, label: o.label ?? String(o.value) } : { value: o, label: String(o) }));
const same = (a, b) => JSON.stringify(a ?? "") === JSON.stringify(b ?? "");

// interrupt 的表單：webui_app.ask 的 {kind: "webui_form", title, message, images, fields}；
// 其他形式的 interrupt 顯示原始值，回覆一段文字（像 JSON 就當 JSON）
function InterruptForm({ waiting, busy, error, onSubmit }) {
  const wt = useWT();
  const v = waiting.value;
  const form = v && typeof v === "object" && v.kind === "webui_form" ? v : null;
  const fields = form?.fields || [];
  const [vals, setVals] = useState(() =>
    Object.fromEntries(
      fields.map((f) => {
        const opts = optionList(f.options);
        let value = f.default ?? (f.type === "checkbox" ? false : "");
        if (f.type === "select" && opts.length && !opts.some((o) => same(o.value, value))) value = opts[0].value;
        return [f.name, value];
      })
    )
  );
  const [raw, setRaw] = useState("");
  const [missing, setMissing] = useState([]);
  const ref = useRef(null);
  useEffect(() => {
    ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, []);

  const submit = () => {
    if (!form) {
      const t = raw.trim();
      let value = t;
      if (/^[[{]/.test(t)) {
        try {
          value = JSON.parse(t);
        } catch {
          /* 不是 JSON 就當文字 */
        }
      }
      onSubmit(value);
      return;
    }
    const miss = fields.filter((f) => f.required && (vals[f.name] === "" || vals[f.name] == null)).map((f) => f.name);
    setMissing(miss);
    if (!miss.length) onSubmit(vals);
  };

  return (
    <div ref={ref} className="space-y-3 rounded-lg border border-amber-500/50 bg-amber-500/5 p-3" data-testid="wf-interrupt">
      <div className="flex flex-wrap items-center gap-2">
        <MessageSquare size={15} className="text-amber-300" />
        <span className="text-sm font-semibold text-amber-200">{form?.title || wt("waitingInput")}</span>
        {waiting.node && <span className="text-xs text-amber-300/70">· {waiting.node}</span>}
        {waiting.pending > 1 && <span className="text-xs text-gray-500">{wt("morePending", { n: waiting.pending - 1 })}</span>}
      </div>
      {form?.message && (
        <div className="markdown break-words text-sm text-gray-200">
          <Markdown remarkPlugins={[remarkGfm]}>{form.message}</Markdown>
        </div>
      )}
      {form?.images?.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {form.images.map((u) => (
            <a key={u} href={u} target="_blank" rel="noreferrer">
              <img src={u} alt="" className="max-h-96 rounded-md border border-ink-700" data-testid="wf-interrupt-image" />
            </a>
          ))}
        </div>
      )}
      {form ? (
        fields.map((f) => (
          <FormField
            key={f.name}
            f={f}
            value={vals[f.name]}
            missing={missing.includes(f.name)}
            onChange={(value) => setVals((s) => ({ ...s, [f.name]: value }))}
          />
        ))
      ) : (
        <>
          {v !== null && v !== undefined && (
            <pre className="max-h-60 overflow-auto whitespace-pre-wrap break-words rounded border border-ink-700 bg-ink-900 p-2 text-[11px] text-gray-300">
              {typeof v === "string" ? v : JSON.stringify(v, null, 2)}
            </pre>
          )}
          <textarea
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
            rows={3}
            placeholder={wt("answerPh")}
            data-testid="wf-interrupt-raw"
            className={`${inputCls} resize-y`}
          />
        </>
      )}
      {error && <div className="text-xs text-red-300">{error}</div>}
      <button
        onClick={submit}
        disabled={busy}
        data-testid="wf-interrupt-submit"
        className="flex items-center gap-1.5 rounded-lg bg-amber-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-amber-500 disabled:opacity-50"
      >
        {busy ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />} {wt("submitAnswer")}
      </button>
    </div>
  );
}

function FormField({ f, value, missing, onChange }) {
  const wt = useWT();
  const opts = optionList(f.options);
  let input;
  if (f.type === "textarea") {
    const len = String(value ?? "").length;
    input = (
      <textarea
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        rows={Math.min(10, Math.max(3, Math.ceil(len / 90) + 1))}
        placeholder={f.placeholder || ""}
        data-testid={`wf-field-${f.name}`}
        className={`${inputCls} resize-y`}
      />
    );
  } else if (f.type === "select") {
    input = (
      <select
        value={JSON.stringify(value ?? "")}
        onChange={(e) => onChange(JSON.parse(e.target.value))}
        data-testid={`wf-field-${f.name}`}
        className={inputCls}
      >
        {opts.map((o) => (
          <option key={JSON.stringify(o.value)} value={JSON.stringify(o.value ?? "")}>
            {o.label}
          </option>
        ))}
      </select>
    );
  } else if (f.type === "choice") {
    input = (
      <div className="flex flex-wrap gap-1.5" data-testid={`wf-field-${f.name}`}>
        {opts.map((o) => (
          <button
            key={JSON.stringify(o.value)}
            type="button"
            onClick={() => onChange(o.value)}
            className={`rounded-md border px-3 py-1.5 text-sm ${
              same(o.value, value) ? "border-amber-400 bg-amber-500/20 text-amber-100" : "border-ink-600 text-gray-300 hover:bg-ink-750"
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
    );
  } else if (f.type === "checkbox") {
    input = (
      <input
        type="checkbox"
        checked={!!value}
        onChange={(e) => onChange(e.target.checked)}
        data-testid={`wf-field-${f.name}`}
        className="h-4 w-4 accent-amber-500"
      />
    );
  } else {
    input = (
      <input
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        placeholder={f.placeholder || ""}
        data-testid={`wf-field-${f.name}`}
        className={inputCls}
      />
    );
  }
  return (
    <div className="space-y-1">
      <div className="text-xs text-gray-300">
        {f.label || f.name}
        {f.required && <span className="text-red-300"> *</span>}
      </div>
      {input}
      {f.help && <div className="text-[11px] text-gray-500">{f.help}</div>}
      {missing && <div className="text-[11px] text-red-300">{wt("fieldRequired")}</div>}
    </div>
  );
}

// 流程圖：節點與邊來自「讀取圖」；有執行（或紀錄）時標出執行中 / 跑過的節點，點節點看它的事件
function GraphPanel({ info, run }) {
  const wt = useWT();
  const show = useWorkflow((s) => s.showDiagram);
  const toggle = useWorkflow((s) => s.toggleDiagram);
  const [picked, setPicked] = useState("");
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    setPicked("");
  }, [info]);
  if (!info?.nodes?.length) return null;
  const events = run?.events || [];
  const nodeEvents = picked ? events.filter((e) => e.node === picked && !e.ns && e.type !== "task") : [];
  const legend = [
    ["#38bdf8", wt("legendActive")],
    ["#fbbf24", wt("legendWaiting")],
    ["#34d399", wt("legendVisited")],
    ["#f87171", wt("legendFailed")],
  ];
  return (
    <div className="rounded-lg border border-ink-700 bg-ink-850" data-testid="wf-graph-panel">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-2 py-1.5">
        <button
          onClick={toggle}
          data-testid="wf-diagram-toggle"
          className="flex items-center gap-1 text-xs font-medium text-gray-300 hover:text-white"
        >
          {show ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          <Workflow size={13} /> {wt("diagram")}
        </button>
        {show && (
          <span className="hidden items-center gap-3 text-[10px] text-gray-500 sm:flex">
            {legend.map(([color, text]) => (
              <span key={text} className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-sm border" style={{ borderColor: color }} />
                {text}
              </span>
            ))}
            <span className="flex items-center gap-1">
              <svg width="18" height="4" className="text-gray-500">
                <line x1="0" y1="2" x2="18" y2="2" stroke="currentColor" strokeWidth="1.3" strokeDasharray="4 3" />
              </svg>
              {wt("legendConditional")}
            </span>
          </span>
        )}
        <div className="flex-1" />
        {info.mermaid && (
          <button
            onClick={async () => {
              if (await copyText(info.mermaid)) {
                setCopied(true);
                setTimeout(() => setCopied(false), 1200);
              }
            }}
            className="flex items-center gap-1 text-[11px] text-gray-500 hover:text-gray-200"
            title={wt("copyMermaidHint")}
          >
            {copied ? <Check size={12} /> : <Copy size={12} />} Mermaid
          </button>
        )}
      </div>
      {show && (
        <div className="border-t border-ink-700 p-2">
          <div className="max-h-[75vh] overflow-auto">
            <GraphDiagram
              nodes={info.nodes}
              edges={info.edges || []}
              events={events}
              status={run?.status}
              selected={picked}
              onSelect={setPicked}
            />
          </div>
          {!picked && <p className="mt-1 text-center text-[10px] text-gray-600">{wt("diagramHint")}</p>}
          {picked && (
            <div className="mt-2 rounded-md border border-ink-700 bg-ink-900 p-2" data-testid="wf-node-detail">
              <div className="mb-1 flex items-center gap-2 text-xs">
                <span className="font-medium text-indigo-300">{picked}</span>
                <span className="text-gray-500">{wt("nodeEvents")}</span>
                <div className="flex-1" />
                <button onClick={() => setPicked("")} className="text-gray-500 hover:text-gray-200">
                  ✕
                </button>
              </div>
              {nodeEvents.length ? (
                <ol className="max-h-72 space-y-1 overflow-y-auto">
                  {nodeEvents.map((e, i) => (
                    <EventRow key={i} e={e} wt={wt} />
                  ))}
                </ol>
              ) : (
                <p className="text-[11px] text-gray-500">{wt("nodeNoEvents")}</p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function RunView({ run }) {
  const wt = useWT();
  const images = run.output !== undefined ? imagesIn(run.output) : [];
  const text = run.output !== undefined ? outputText(run.output) : "";
  return (
    <div className="space-y-2" data-testid="wf-run-view">
      {run.progress && (
        <div className="flex items-center gap-2 text-[11px] text-gray-400">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-700">
            <div className="h-full rounded-full bg-emerald-500" style={{ width: `${Math.round((run.progress.value || 0) * 100)}%` }} />
          </div>
          {run.progress.step != null && `${run.progress.step}/${run.progress.steps}`}
        </div>
      )}
      <ol className="space-y-1 rounded-lg border border-ink-700 bg-ink-850 p-2" data-testid="wf-events">
        {run.events.filter((e) => !["start", "done", "error"].includes(e.type)).map((e, i) => (
          <EventRow key={i} e={e} wt={wt} />
        ))}
        {run.status === "running" && run.events.length === 0 && (
          <li className="text-xs text-gray-500">
            <Loader2 size={12} className="inline animate-spin" />
          </li>
        )}
      </ol>
      {run.status === "error" && run.error && <ErrorBox text={run.error} trace={run.trace} />}
      {run.status === "stopped" && <div className="text-xs text-gray-400">{wt("stopped")}</div>}
      {run.output !== undefined && (
        <div className="space-y-2 rounded-lg border border-emerald-800/50 bg-ink-850 p-3" data-testid="wf-output">
          <div className="text-xs font-semibold text-emerald-300">{wt("output")}</div>
          {images.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {images.map((u) => (
                <a key={u} href={u} target="_blank" rel="noreferrer">
                  <img src={u} alt="" className="max-h-72 rounded-md border border-ink-700" />
                </a>
              ))}
            </div>
          )}
          {text && (
            <div className="markdown break-words text-sm">
              <Markdown remarkPlugins={[remarkGfm]}>{text}</Markdown>
            </div>
          )}
          <details>
            <summary className="cursor-pointer text-[11px] text-gray-500">{wt("rawJson")}</summary>
            <pre className="mt-1 max-h-80 overflow-auto whitespace-pre-wrap break-words text-[11px] text-gray-300">
              {JSON.stringify(run.output, null, 2)}
            </pre>
          </details>
        </div>
      )}
    </div>
  );
}

function Json({ value }) {
  const [open, setOpen] = useState(false);
  const s = JSON.stringify(value);
  if (s === undefined || s === "null") return null;
  return (
    <span className="min-w-0">
      <button onClick={() => setOpen((v) => !v)} className="mr-1 inline-flex align-middle text-gray-500 hover:text-gray-300">
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </button>
      {open ? (
        <pre className="mt-1 max-h-72 overflow-auto whitespace-pre-wrap break-words text-[11px] text-gray-300">
          {JSON.stringify(value, null, 2)}
        </pre>
      ) : (
        <span className="text-gray-400">{s.length > 160 ? s.slice(0, 160) + "…" : s}</span>
      )}
    </span>
  );
}

function EventRow({ e, wt }) {
  const where = e.node ? <span className="font-medium text-indigo-300">{e.ns ? `${e.ns}/` : ""}{e.node}</span> : null;
  const row = "flex min-w-0 items-start gap-1.5 text-xs leading-relaxed";
  switch (e.type) {
    case "node":
      return (
        <li className={row}>
          <ChevronRight size={13} className="mt-0.5 shrink-0 text-indigo-400" />
          <span className="min-w-0 break-words">
            {where} <Json value={e.update} />
          </span>
        </li>
      );
    case "llm":
      return (
        <li className={`${row} text-gray-400`}>
          <Brain size={13} className="mt-0.5 shrink-0 text-violet-300" />
          <span>
            {where} · {wt("llmCall")} ({e.engine} / {e.model}){e.images ? ` · ${wt("llmImages", { n: e.images })}` : ""}
            {e.tools ? ` · ${wt("llmTools", { n: e.tools })}` : ""}
          </span>
        </li>
      );
    case "llm_done":
      return (
        <li className={`${row} text-gray-500`}>
          <Check size={13} className="mt-0.5 shrink-0 text-violet-300" />
          <span className="min-w-0 break-words">
            {wt("llmDone", { n: e.chars, s: e.seconds })}
            {e.tool_calls?.length > 0 && <span className="text-amber-200/80"> → {e.tool_calls.join(", ")}</span>}
            {e.preview && <> — <span className="text-gray-400">{e.preview}</span></>}
          </span>
        </li>
      );
    case "tool_call":
      return (
        <li className={row}>
          <Wrench size={13} className="mt-0.5 shrink-0 text-amber-300" />
          <span className="min-w-0 break-words">
            {where} {wt("toolCall")} <span className="font-mono text-amber-200">{e.name}</span> <Json value={e.args} />
          </span>
        </li>
      );
    case "tool_result":
      return (
        <li className={`${row} text-gray-400`}>
          <CornerDownRight size={13} className="mt-0.5 shrink-0 text-amber-300/70" />
          <span className="min-w-0 break-words">
            <span className="font-mono text-gray-300">{e.name}</span>{" "}
            {(e.text || "").length > 200 ? (
              <details className="inline">
                <summary className="inline cursor-pointer">{e.text.slice(0, 200)}…</summary>
                <pre className="mt-1 max-h-72 overflow-auto whitespace-pre-wrap break-words text-[11px] text-gray-300">{e.text}</pre>
              </details>
            ) : (
              e.text || "—"
            )}
          </span>
        </li>
      );
    case "gallery":
    case "candidates":
      return (
        <li className={`${row} text-gray-400`}>
          <span className="shrink-0">🖼</span>
          <span className="min-w-0 break-words">
            {where} {e.title || e.kind || e.type} · {wt("itemsCount", { n: (e.items || []).length })}
          </span>
        </li>
      );
    case "token":
      return (
        <li className={row}>
          <FileText size={13} className="mt-0.5 shrink-0 text-gray-400" />
          <span className="min-w-0 whitespace-pre-wrap break-words text-gray-200">
            {where} {e.text}
          </span>
        </li>
      );
    case "image":
      return (
        <li className={row}>
          <span className="shrink-0">🖼</span>
          <span className="min-w-0">
            {where}
            <a href={e.url} target="_blank" rel="noreferrer" className="mt-1 block">
              <img src={e.url} alt="" className="max-h-48 rounded-md border border-ink-700" data-testid="wf-event-image" />
            </a>
          </span>
        </li>
      );
    case "sources":
      return (
        <li className={row}>
          <Search size={13} className="mt-0.5 shrink-0 text-sky-300" />
          <span className="min-w-0 break-words">
            {where} {wt("sources")}「{e.query}」:{" "}
            {(e.results || []).slice(0, 5).map((r, i) => (
              <a key={i} href={r.url} target="_blank" rel="noreferrer" className="mr-2 text-sky-300 hover:underline">
                {r.title || r.url}
              </a>
            ))}
          </span>
        </li>
      );
    case "note":
    case "custom":
      return (
        <li className={`${row} text-gray-300`}>
          <span className="shrink-0 text-gray-500">•</span>
          <span className="min-w-0 break-words">
            {where} {e.type === "note" ? e.text : <Json value={e.data} />}
          </span>
        </li>
      );
    case "log":
    case "stderr":
      return (
        <li className={`${row} font-mono text-[11px] ${e.type === "stderr" ? "text-amber-200/70" : "text-gray-500"}`}>
          <span className="min-w-0 whitespace-pre-wrap break-all">{e.text}</span>
        </li>
      );
    case "call_error":
      return (
        <li className={`${row} text-red-300`}>
          <AlertCircle size={13} className="mt-0.5 shrink-0" />
          <span className="min-w-0 break-words">
            {where} webui_app.{e.fn}: {e.message}
          </span>
        </li>
      );
    case "interrupt": {
      const title = e.value?.kind === "webui_form" ? e.value.title : "";
      return (
        <li className={`${row} text-amber-300`}>
          <MessageSquare size={13} className="mt-0.5 shrink-0" />
          <span className="min-w-0 break-words">
            {where} {e.pending === undefined ? wt("interruptNoResume") : wt("interrupt")}
            {title ? `：${title}` : <Json value={e.value} />}
          </span>
        </li>
      );
    }
    case "resume":
      return (
        <li className={`${row} text-amber-200/80`}>
          <Send size={13} className="mt-0.5 shrink-0" />
          <span className="min-w-0 break-words">
            {where} {wt("answered")} <Json value={e.value} />
          </span>
        </li>
      );
    default:
      return null;
  }
}

// ---------------- 工作流資料夾 ----------------

function FolderCard() {
  const wt = useWT();
  const folder = useWorkflow((s) => s.folder);
  const setFolder = useWorkflow((s) => s.setFolder);
  const [picking, setPicking] = useState(false);
  const [err, setErr] = useState("");
  if (!folder) return null;
  const change = async (path) => {
    setErr("");
    try {
      await setFolder(path);
    } catch (e) {
      setErr(e.message);
    }
  };
  return (
    <div className="space-y-1 rounded-lg border border-ink-700 p-2" data-testid="wf-folder">
      <div className="flex items-center gap-1.5 text-xs font-medium text-gray-300">
        <FolderOpen size={13} /> {wt("folder")}
        {folder.override && <span className="rounded bg-ink-700 px-1 text-[10px] text-amber-200">{wt("custom")}</span>}
      </div>
      <div className="break-all font-mono text-[10px] leading-snug text-gray-400" data-testid="wf-folder-path" title={folder.dir}>
        {folder.dir}
      </div>
      {!folder.writable && <div className="text-[10px] text-amber-300">{wt("folderReadonly")}</div>}
      <div className="flex gap-1.5">
        <button onClick={() => setPicking(true)} data-testid="wf-folder-change" className={`${btnCls} flex-1`}>
          {wt("changeFolder")}
        </button>
        {folder.override && (
          <button onClick={() => change("")} data-testid="wf-folder-reset" className={btnCls} title={folder.default}>
            <RotateCcw size={12} /> {wt("defaultFolder")}
          </button>
        )}
      </div>
      <p className="text-[10px] leading-snug text-gray-500">{wt("folderHint")}</p>
      {folder.docker && (
        <p className="text-[10px] leading-snug text-gray-500" data-testid="wf-folder-docker">
          {wt("folderDockerHint")}
        </p>
      )}
      {err && <ErrorBox text={err} />}
      {picking && (
        <DirectoryPicker
          initialPath={folder.dir}
          title={wt("pickFolder")}
          onClose={() => setPicking(false)}
          onPick={async (path) => {
            setPicking(false);
            await change(path);
          }}
        />
      )}
    </div>
  );
}

// ---------------- 執行紀錄 ----------------

function HistoryPanel({ onReuse }) {
  const wt = useWT();
  const w = useWorkflow();
  const rec = w.record;
  return (
    <div className="flex flex-col gap-3 lg:flex-row">
      <div className="space-y-1.5 lg:w-80 lg:shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400">{wt("runsCount", { n: w.runs.length })}</span>
          <div className="flex-1" />
          <button onClick={() => w.loadRuns()} className="text-gray-500 hover:text-gray-200" title={wt("rescan")}>
            {w.runsLoading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
          </button>
          {w.runs.length > 0 && (
            <button
              onClick={() => window.confirm(wt("clearRunsConfirm")) && w.clearRecords()}
              className="text-[11px] text-gray-500 hover:text-red-300"
            >
              {wt("clearRuns")}
            </button>
          )}
        </div>
        {w.runs.length === 0 && !w.runsLoading && <p className="text-xs text-gray-500">{wt("noRuns")}</p>}
        <ul className="max-h-[60vh] space-y-1 overflow-y-auto" data-testid="wf-runs">
          {w.runs.map((r) => (
            <li key={r.id}>
              <button
                onClick={() => w.openRecord(r.id)}
                data-testid="wf-run-item"
                className={`w-full rounded-md border px-2 py-1.5 text-left text-xs ${
                  rec?.id === r.id ? "border-indigo-500/60 bg-ink-750" : "border-ink-700 hover:bg-ink-800"
                }`}
              >
                <span className="flex items-center gap-1.5">
                  <span className={`font-medium ${RUN_COLOR[r.status] || ""}`}>{wt(`status_${r.status}`)}</span>
                  <span className="text-gray-300">{r.graph}</span>
                  {r.source === "chat" && <span className="rounded bg-ink-700 px-1 text-[10px] text-gray-400">{wt("fromChat")}</span>}
                  <span className="flex-1" />
                  <span className="text-[10px] text-gray-500">{ago(r.started_at, wt)}</span>
                </span>
                <span className="mt-0.5 block truncate text-[11px] text-gray-500">{r.input_preview || "—"}</span>
                <span className="mt-0.5 flex items-center gap-1 text-[10px] text-gray-600">
                  {r.engine} / {r.model}
                  {r.seconds != null && ` · ${r.seconds}s`}
                </span>
                {r.images?.length > 0 && (
                  <span className="mt-1 flex gap-1">
                    {r.images.map((u) => (
                      <img key={u} src={u} alt="" className="h-10 w-10 rounded object-cover" />
                    ))}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div className="min-w-0 flex-1">
        {!rec ? (
          <p className="text-xs text-gray-500">{wt("pickRun")}</p>
        ) : (
          <div className="space-y-2" data-testid="wf-record">
            <div className="flex flex-wrap items-center gap-2">
              <span className={`text-sm font-medium ${RUN_COLOR[rec.status] || ""}`}>{wt(`status_${rec.status}`)}</span>
              <span className="text-sm text-gray-200">{rec.graph}</span>
              <span className="text-[11px] text-gray-500">
                {rec.started_at ? new Date(rec.started_at * 1000).toLocaleString() : ""} · {rec.engine} / {rec.model}
              </span>
              <div className="flex-1" />
              <button
                onClick={() => {
                  w.reuseRecord(rec);
                  onReuse();
                }}
                data-testid="wf-reuse"
                className={btnCls}
              >
                <Play size={13} /> {wt("reuseInput")}
              </button>
              <button onClick={() => w.deleteRecord(rec.id)} className={`${btnCls} hover:text-red-300`} title={wt("delete")}>
                <Trash2 size={13} />
              </button>
            </div>
            <details>
              <summary className="cursor-pointer text-[11px] text-gray-500">{wt("input")}</summary>
              <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded border border-ink-700 bg-ink-850 p-2 text-[11px] text-gray-300">
                {typeof rec.input === "string" ? rec.input : JSON.stringify(rec.input, null, 2)}
              </pre>
            </details>
            <GraphPanel key={rec.id} info={w.graphs?.[rec.graph]} run={rec} />
            <RunView
              run={{
                status: rec.status,
                events: rec.events || [],
                output: rec.status === "done" ? rec.output : undefined,
                error: rec.error,
                trace: rec.trace,
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------- 檔案 ----------------

function FilesPanel() {
  const wt = useWT();
  const w = useWorkflow();
  const [path, setPath] = useState("");
  const [content, setContent] = useState("");
  const [orig, setOrig] = useState("");
  const [secret, setSecret] = useState(false);
  const [newPath, setNewPath] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const files = w.project.files || [];

  const open = async (f) => {
    setErr("");
    setMsg("");
    setPath(f.path);
    setSecret(!!f.secret);
    if (f.secret) {
      setContent("");
      setOrig("");
      return;
    }
    try {
      const r = await readWorkflowFile(w.selected, f.path);
      setContent(r.content);
      setOrig(r.content);
    } catch (e) {
      setContent("");
      setOrig("");
      setErr(e.message);
    }
  };

  const save = async () => {
    setErr("");
    try {
      await w.saveFile(path, content);
      setOrig(content);
      setMsg(wt("saved"));
      setTimeout(() => setMsg(""), 1500);
      if (secret) setContent("");
    } catch (e) {
      setErr(e.message);
    }
  };

  return (
    <div className="flex flex-col gap-3 md:flex-row">
      <div className="space-y-2 md:w-60 md:shrink-0">
        <ul className="max-h-[50vh] space-y-0.5 overflow-y-auto" data-testid="wf-files">
          {files.map((f) => (
            <li key={f.path}>
              <button
                onClick={() => open(f)}
                className={`flex w-full items-center gap-1.5 rounded px-2 py-1 text-left font-mono text-xs ${
                  f.path === path ? "bg-ink-700 text-white" : "text-gray-300 hover:bg-ink-800"
                }`}
              >
                {f.secret ? <Lock size={11} className="shrink-0 text-amber-300" /> : <FileText size={11} className="shrink-0 text-gray-500" />}
                <span className="min-w-0 flex-1 truncate">{f.path}</span>
                <span className="shrink-0 text-[10px] text-gray-600">{f.size >= 1024 ? `${Math.round(f.size / 1024)}k` : f.size}</span>
              </button>
            </li>
          ))}
        </ul>
        <div className="flex gap-1">
          <input value={newPath} onChange={(e) => setNewPath(e.target.value)} placeholder={wt("newFilePh")} className={`${inputCls} text-xs`} />
          <button
            onClick={() => {
              const p = newPath.trim();
              if (!p) return;
              setPath(p);
              setSecret(/(^|\/)\.env(\.|$)/.test(p));
              setContent("");
              setOrig(null);
              setNewPath("");
            }}
            className={btnCls}
            title={wt("newFile")}
          >
            <Plus size={13} />
          </button>
        </div>
      </div>
      <div className="min-w-0 flex-1 space-y-1.5">
        {!path ? (
          <p className="text-xs text-gray-500">{wt("selectFile")}</p>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <code className="min-w-0 flex-1 truncate text-xs text-gray-300">{path}</code>
              {msg && <span className="text-[11px] text-emerald-300">{msg}</span>}
              <button onClick={save} disabled={!secret && content === orig} data-testid="wf-save" className={btnCls}>
                {wt("save")}
              </button>
              {path !== "langgraph.json" && orig !== null && (
                <button
                  onClick={async () => {
                    if (!window.confirm(wt("deleteFileConfirm", { path }))) return;
                    await w.deleteFile(path).catch((e) => setErr(e.message));
                    setPath("");
                  }}
                  className={`${btnCls} hover:text-red-300`}
                >
                  <Trash2 size={13} />
                </button>
              )}
            </div>
            {secret && <p className="text-[11px] text-amber-200/80">{wt("secretFile")}</p>}
            {err && <ErrorBox text={err} />}
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              spellCheck={false}
              data-testid="wf-editor"
              className={`${inputCls} h-[55vh] resize-y font-mono text-xs leading-relaxed`}
            />
          </>
        )}
      </div>
    </div>
  );
}
