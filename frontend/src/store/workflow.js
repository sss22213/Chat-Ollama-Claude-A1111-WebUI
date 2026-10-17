// LangGraph 工作流頁面狀態：專案清單、選中的專案 / 圖、輸入、安裝紀錄、執行事件。
// 只把「選了哪個專案 / 圖」與各圖的輸入草稿存在 localStorage；專案本身在伺服器上。
import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import {
  cancelWorkflowRun,
  clearWorkflowRuns,
  createWorkflowProject,
  deleteWorkflowRun,
  duplicateWorkflowProject,
  fetchWorkflowRun,
  fetchWorkflowRuns,
  renameWorkflowProject,
  resumeWorkflowRun,
  setWorkflowsDir,
  deleteWorkflowFile,
  deleteWorkflowProject,
  fetchWorkflowProject,
  fetchWorkflows,
  inspectWorkflow,
  installWorkflow,
  runWorkflow,
  setWorkflowsEnabled,
  uploadWorkflowProject,
  writeWorkflowFile,
} from "../lib/workflowApi";

const MAX_EVENTS = 2000;

// JSON schema → 輸入範本（每個欄位放一個空值；messages 放一則使用者訊息）
export function inputTemplate(schema) {
  const props = schema?.properties || {};
  const out = {};
  for (const [k, p] of Object.entries(props)) {
    if (k === "messages") out[k] = [{ role: "user", content: "" }];
    else if (p?.type === "string" || p?.anyOf?.some((a) => a?.type === "string")) out[k] = "";
    else if (p?.type === "integer" || p?.type === "number") out[k] = 0;
    else if (p?.type === "boolean") out[k] = false;
    else if (p?.type === "array") out[k] = [];
    else out[k] = {};
  }
  return JSON.stringify(out, null, 2);
}

// 輸入框內容 → 送出的 input：像 JSON 物件就解析，否則當一段文字（後端對應到輸入欄位）
export function parseInput(text) {
  const t = (text || "").trim();
  if (t.startsWith("{")) return JSON.parse(t); // 解析失敗丟出去給 UI 顯示
  return t;
}

export const useWorkflow = create(
  persist(
    (set, get) => ({
      enabled: false,
      folder: null, // {dir, default, override, writable}
      query: "", // 專案清單搜尋
      projects: [],
      templates: [], // 新增專案可選的範本 [{id, description}]
      loaded: false,
      error: "",
      selected: "", // 專案 slug
      project: null, // 專案詳細（檔案、設定、venv）
      graphs: null, // inspect 結果 {id: {...}}
      inspecting: false,
      inspectError: "",
      graph: "", // 選中的圖
      inputs: {}, // {"slug:graph": 輸入草稿}
      installing: false,
      installLog: [],
      // {id, project, graph, status: running|done|error, events, output, error,
      //  waiting: 正在等回覆的 interrupt 事件或 null, answering, answerError}
      run: null,
      _abort: null,
      showDiagram: true, // 執行分頁的流程圖展開與否
      toggleDiagram() {
        set((st) => ({ showDiagram: !st.showDiagram }));
      },
      runs: [], // 執行紀錄摘要（新到舊）
      runsLoading: false,
      record: null, // 打開的一筆完整紀錄

      async load() {
        try {
          const data = await fetchWorkflows();
          set({
            enabled: data.enabled,
            folder: data.folder,
            projects: data.projects,
            templates: data.templates || [],
            loaded: true,
            error: "",
          });
          const { selected } = get();
          const keep = data.projects.some((p) => p.slug === selected);
          const next = keep ? selected : data.projects[0]?.slug || "";
          if (next) await get().select(next, { force: !keep || !get().project });
          else set({ selected: "", project: null, graphs: null });
        } catch (e) {
          set({ loaded: true, error: e.message });
        }
      },
      async setEnabled(on) {
        const r = await setWorkflowsEnabled(on);
        set({ enabled: r.enabled });
      },
      setQuery(query) {
        set({ query });
      },
      // 換工作流資料夾（空字串＝預設）：清單、選取全部重來
      async setFolder(path) {
        const folder = await setWorkflowsDir(path);
        set({ folder, selected: "", project: null, graphs: null, runs: [], record: null });
        await get().load();
      },
      async rename(newSlug) {
        const slug = get().selected;
        await renameWorkflowProject(slug, newSlug);
        // 各圖的輸入草稿跟著改名
        set((st) => ({
          inputs: Object.fromEntries(
            Object.entries(st.inputs).map(([k, v]) => [k.startsWith(`${slug}:`) ? `${newSlug}:${k.slice(slug.length + 1)}` : k, v])
          ),
        }));
        await get().load();
        await get().select(newSlug, { force: true });
      },
      async duplicate(newSlug) {
        await duplicateWorkflowProject(get().selected, newSlug);
        await get().load();
        await get().select(newSlug, { force: true });
      },
      async loadRuns() {
        const slug = get().selected;
        if (!slug) return;
        set({ runsLoading: true });
        try {
          const runs = await fetchWorkflowRuns(slug);
          if (get().selected === slug) set({ runs });
        } finally {
          set({ runsLoading: false });
        }
      },
      async openRecord(id) {
        set({ record: id ? await fetchWorkflowRun(get().selected, id) : null });
      },
      async deleteRecord(id) {
        await deleteWorkflowRun(get().selected, id);
        if (get().record?.id === id) set({ record: null });
        await get().loadRuns();
      },
      async clearRecords() {
        await clearWorkflowRuns(get().selected);
        set({ record: null });
        await get().loadRuns();
      },
      // 拿紀錄的圖與輸入填回「執行」分頁（不自動執行）
      reuseRecord(rec) {
        const text = typeof rec.input === "string" ? rec.input : JSON.stringify(rec.input ?? {}, null, 2);
        set((st) => ({ graph: rec.graph, inputs: { ...st.inputs, [`${st.selected}:${rec.graph}`]: text } }));
      },
      async refreshProject() {
        const slug = get().selected;
        if (!slug) return;
        const project = await fetchWorkflowProject(slug);
        set((st) => ({
          project,
          projects: st.projects.map((p) =>
            p.slug === slug ? { ...p, venv: project.venv, graphs: Object.keys(project.config?.graphs || {}) } : p
          ),
        }));
        return project;
      },
      async select(slug, { force = false } = {}) {
        if (!force && slug === get().selected && get().project) return;
        set({ selected: slug, project: null, graphs: null, inspectError: "", installLog: [], runs: [], record: null });
        if (get().run?.status !== "running") set({ run: null });
        try {
          const project = await get().refreshProject();
          const ids = Object.keys(project?.config?.graphs || {});
          if (!ids.includes(get().graph)) set({ graph: ids[0] || "" });
          if (get().enabled && project?.venv?.state === "ready") get().inspect();
        } catch (e) {
          set({ error: e.message });
        }
      },
      async create(slug, template) {
        await createWorkflowProject(slug, template);
        await get().load();
        await get().select(slug, { force: true });
      },
      async upload(slug, payload) {
        await uploadWorkflowProject(slug, payload);
        await get().load();
        await get().select(slug, { force: true });
      },
      async remove(slug) {
        await deleteWorkflowProject(slug);
        if (get().selected === slug) set({ selected: "", project: null, graphs: null });
        await get().load();
      },
      async saveFile(path, content) {
        const project = await writeWorkflowFile(get().selected, path, content);
        set({ project });
        await get().load();
      },
      async deleteFile(path) {
        const project = await deleteWorkflowFile(get().selected, path);
        set({ project });
      },
      setGraph(graph) {
        set({ graph });
      },
      setInput(text) {
        const key = `${get().selected}:${get().graph}`;
        set((st) => ({ inputs: { ...st.inputs, [key]: text } }));
      },
      async inspect() {
        const slug = get().selected;
        if (!slug) return;
        set({ inspecting: true, inspectError: "" });
        try {
          const { graphs } = await inspectWorkflow(slug);
          if (get().selected === slug) set({ graphs });
        } catch (e) {
          set({ inspectError: e.message });
        } finally {
          set({ inspecting: false });
        }
      },
      install() {
        const slug = get().selected;
        if (!slug || get().installing) return;
        set({ installing: true, installLog: [] });
        const add = (line) => set((st) => ({ installLog: [...st.installLog, line].slice(-1500) }));
        installWorkflow(
          slug,
          (e) => {
            if (e.type === "log") add({ text: e.text });
            else if (e.type === "error") add({ text: e.message, error: true });
            else if (e.type === "done") add({ text: "✓", done: true });
          },
          async () => {
            set({ installing: false });
            await get().refreshProject().catch(() => {});
            await get().load();
            if (get().project?.venv?.state === "ready") get().inspect();
          },
          (err) => {
            add({ text: err.message, error: true });
            set({ installing: false });
          }
        );
      },
      // opts：{engine, model, think, effort, numCtx, imageSettings}
      start(opts) {
        const { selected, graph, run } = get();
        if (!selected || !graph || run?.status === "running") return;
        let input;
        try {
          input = parseInput(get().inputs[`${selected}:${graph}`] || "");
        } catch (e) {
          set({ run: { status: "error", events: [], error: `JSON: ${e.message}` } });
          return;
        }
        set({ run: { id: "", project: selected, graph, status: "running", events: [], output: undefined, error: "" } });
        const patch = (fn) => set((st) => ({ run: st.run ? { ...st.run, ...fn(st.run) } : st.run }));
        const abort = runWorkflow(
          {
            project: selected,
            graph,
            input,
            engine: opts.engine,
            model: opts.model,
            think: opts.think,
            effort: opts.effort,
            num_ctx: opts.numCtx,
            image_settings: opts.imageSettings,
          },
          (e) => {
            if (e.type === "run") patch(() => ({ id: e.id }));
            else if (e.type === "ping") return; // 等回覆時保持連線用
            // 有 pending 的 interrupt 才能回覆（工作流頁面執行、有 checkpointer）
            else if (e.type === "interrupt")
              patch((r) => ({ waiting: e.pending !== undefined ? e : null, events: [...r.events, e].slice(-MAX_EVENTS) }));
            else if (e.type === "resume")
              patch((r) => ({ waiting: null, answering: false, events: [...r.events, e].slice(-MAX_EVENTS) }));
            else if (e.type === "done") patch((r) => ({ output: e.output, events: [...r.events, e] }));
            else if (e.type === "error") patch((r) => ({ error: e.message, trace: e.traceback, events: [...r.events, e] }));
            else if (e.type === "progress") patch(() => ({ progress: e }));
            else if (e.type === "token") {
              // 同一個節點連續的 token 併成一段
              patch((r) => {
                const last = r.events[r.events.length - 1];
                if (last?.type === "token" && last.node === e.node) {
                  return { events: [...r.events.slice(0, -1), { ...last, text: last.text + e.text }] };
                }
                return { events: [...r.events, e].slice(-MAX_EVENTS) };
              });
            } else {
              patch((r) => ({
                events: [...r.events, e].slice(-MAX_EVENTS),
                progress: e.type === "image" ? null : r.progress,
              }));
            }
          },
          () => {
            patch((r) => ({
              status: r.error ? "error" : r.output !== undefined ? "done" : "stopped",
              progress: null,
              waiting: null,
            }));
            set({ _abort: null });
            // 清單上的「最近一次執行」與紀錄分頁跟著更新
            get().load();
            get().loadRuns();
          },
          (err) => {
            patch(() => ({ status: "error", error: err.message, progress: null, waiting: null }));
            set({ _abort: null });
          }
        );
        set({ _abort: abort });
      },
      // 回覆 interrupt；工作流收到後會送 resume 事件（那時才清掉 waiting）
      async answer(value) {
        const run = get().run;
        if (!run?.id || !run.waiting || run.answering) return;
        const patch = (p) => set((st) => ({ run: st.run ? { ...st.run, ...p } : st.run }));
        patch({ answering: true, answerError: "" });
        try {
          await resumeWorkflowRun(run.id, value);
        } catch (e) {
          patch({ answering: false, answerError: e.message });
        }
      },
      async stop() {
        const { run, _abort } = get();
        if (run?.id) await cancelWorkflowRun(run.id).catch(() => {});
        _abort?.abort();
      },
    }),
    {
      name: "webui-workflow",
      storage: createJSONStorage(() => localStorage),
      partialize: (st) => ({ selected: st.selected, graph: st.graph, inputs: st.inputs, showDiagram: st.showDiagram }),
    }
  )
);
