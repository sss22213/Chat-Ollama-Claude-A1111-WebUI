// LangGraph 工作流 API：專案、檔案、安裝依賴、檢視圖、執行（SSE）。

const enc = encodeURIComponent;

async function req(method, url, body) {
  const r = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
  return data;
}

const proj = (slug) => `/api/langgraph/projects/${enc(slug)}`;

export const fetchWorkflows = () => req("GET", "/api/langgraph");
export const setWorkflowsEnabled = (enabled) => req("PUT", "/api/langgraph/enabled", { enabled });
export const createWorkflowProject = (slug, template) =>
  req("POST", "/api/langgraph/projects", { slug, template });
export const fetchWorkflowProject = (slug) => req("GET", proj(slug));
export const deleteWorkflowProject = (slug) => req("DELETE", proj(slug));
// payload：{files: [{path, b64}]} 或 {zip_b64}；replace＝先清掉原本的檔案
export const uploadWorkflowProject = (slug, payload) => req("POST", `${proj(slug)}/upload`, payload);
export const readWorkflowFile = (slug, path) => req("GET", `${proj(slug)}/file?path=${enc(path)}`);
export const writeWorkflowFile = (slug, path, content) =>
  req("PUT", `${proj(slug)}/file`, { path, content });
export const deleteWorkflowFile = (slug, path) =>
  req("DELETE", `${proj(slug)}/file?path=${enc(path)}`);
export const inspectWorkflow = (slug) => req("GET", `${proj(slug)}/inspect`);
export const cancelWorkflowRun = (id) => req("POST", `/api/langgraph/runs/${enc(id)}/cancel`);
// 回覆正在等的 interrupt（webui_app.ask 的表單值，或任意 JSON / 文字）
export const resumeWorkflowRun = (id, value) => req("POST", `/api/langgraph/runs/${enc(id)}/resume`, { value });
// 工作流資料夾（空字串＝回到預設）
export const setWorkflowsDir = (path) => req("PUT", "/api/langgraph/dir", { path });
export const renameWorkflowProject = (slug, newSlug) =>
  req("POST", `${proj(slug)}/rename`, { new_slug: newSlug });
export const duplicateWorkflowProject = (slug, newSlug) =>
  req("POST", `${proj(slug)}/duplicate`, { new_slug: newSlug });
// zip 下載網址（不含 .env、venv）
export const workflowExportUrl = (slug) => `${proj(slug)}/export`;
// 執行紀錄
export const fetchWorkflowRuns = (slug) => req("GET", `${proj(slug)}/runs`);
export const fetchWorkflowRun = (slug, id) => req("GET", `${proj(slug)}/runs/${enc(id)}`);
export const deleteWorkflowRun = (slug, id) => req("DELETE", `${proj(slug)}/runs/${enc(id)}`);
export const clearWorkflowRuns = (slug) => req("DELETE", `${proj(slug)}/runs`);

// POST 一個 SSE 端點；回傳 AbortController（abort＝中斷連線，後端會停掉執行）
function streamSSE(url, body, onEvent, onDone, onError) {
  const controller = new AbortController();
  (async () => {
    try {
      const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
        signal: controller.signal,
      });
      if (!resp.ok || !resp.body) throw new Error(`伺服器錯誤 (${resp.status})`);
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith("data:")) continue;
          try {
            onEvent(JSON.parse(line.slice(5).trim()));
          } catch {
            /* 略過解析失敗的片段 */
          }
        }
      }
      onDone?.();
    } catch (e) {
      if (e.name === "AbortError") onDone?.();
      else onError?.(e);
    }
  })();
  return controller;
}

export const installWorkflow = (slug, onEvent, onDone, onError) =>
  streamSSE(`${proj(slug)}/install`, {}, onEvent, onDone, onError);

// payload：{project, graph} 或 {target}、input、engine、model、think、effort、num_ctx、image_settings
export const runWorkflow = (payload, onEvent, onDone, onError) =>
  streamSSE("/api/langgraph/run", payload, onEvent, onDone, onError);

// 讀取資料夾 / zip 上傳用：File → base64（不含 data: 前綴）
export function fileToB64(file) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result).split(",", 2)[1] || "");
    fr.onerror = () => reject(fr.error);
    fr.readAsDataURL(file);
  });
}

// 執行結果裡 app 生成的圖（/images/…）
export function imagesIn(value, out = []) {
  if (typeof value === "string") {
    if (/^\/images\/[^\s"']+\.(png|jpe?g|webp)$/i.test(value) && !out.includes(value)) out.push(value);
  } else if (Array.isArray(value)) {
    value.forEach((v) => imagesIn(v, out));
  } else if (value && typeof value === "object") {
    Object.values(value).forEach((v) => imagesIn(v, out));
  }
  return out;
}

// 最終輸出 → 給人看的文字：messages 取最後一則 AI 回覆；其他字串欄位逐一列出
export function outputText(output) {
  if (output == null) return "";
  if (typeof output === "string") return output;
  if (typeof output !== "object") return String(output);
  const msgs = Array.isArray(output.messages) ? output.messages : null;
  if (msgs?.length) {
    const ai = [...msgs].reverse().find((m) => m && (m.type === "ai" || m.role === "assistant"));
    if (ai) return typeof ai.content === "string" ? ai.content : JSON.stringify(ai.content);
  }
  const parts = [];
  for (const [k, v] of Object.entries(output)) {
    if (k === "messages") continue;
    if (typeof v === "string") {
      if (!imagesIn(v).length && v.trim()) parts.push(`**${k}**\n\n${v}`);
    } else if (typeof v === "number" || typeof v === "boolean") {
      parts.push(`**${k}**: ${v}`);
    } else if (v != null && !imagesIn(v).length) {
      parts.push(`**${k}**\n\n\`\`\`json\n${JSON.stringify(v, null, 2)}\n\`\`\``);
    }
  }
  return parts.join("\n\n");
}
