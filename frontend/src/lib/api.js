// 後端 API：REST + SSE 串流

export async function fetchModels(engine = "ollama") {
  const r = await fetch(`/api/models?engine=${encodeURIComponent(engine)}`);
  if (!r.ok) throw new Error("無法取得模型清單");
  return r.json();
}

export async function fetchEngines() {
  try {
    const r = await fetch("/api/engines");
    return await r.json();
  } catch {
    return { ollama: true, claude_cli: false };
  }
}

export async function fetchSdModels() {
  const r = await fetch("/api/sd-models");
  if (!r.ok) throw new Error("無法取得 SD 模型");
  return r.json();
}

export async function fetchSamplers() {
  const r = await fetch("/api/samplers");
  if (!r.ok) throw new Error("無法取得取樣器");
  return r.json();
}

export async function fetchDefaults() {
  const r = await fetch("/api/defaults");
  if (!r.ok) throw new Error("無法取得預設值");
  return r.json();
}

// ---- 圖片儲存位置 ----
export async function fetchStorage() {
  const r = await fetch("/api/storage");
  if (!r.ok) throw new Error("無法取得儲存設定");
  return r.json();
}

export async function setStorage(imageDir) {
  const r = await fetch("/api/storage", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ image_dir: imageDir }),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "設定失敗");
  return r.json();
}

// ---- 伺服器端資料夾瀏覽 ----
export async function browseDir(path) {
  const url = path ? `/api/browse?path=${encodeURIComponent(path)}` : "/api/browse";
  const r = await fetch(url);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "無法瀏覽");
  return r.json();
}

export async function makeDir(path, name) {
  const r = await fetch("/api/browse/mkdir", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, name }),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "建立失敗");
  return r.json();
}

// ---- 服務來源（Ollama / A1111）----
export async function fetchSources() {
  const r = await fetch("/api/sources");
  if (!r.ok) throw new Error("無法取得來源設定");
  return r.json();
}

export async function saveSources(payload) {
  const r = await fetch("/api/sources", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "儲存失敗");
  return r.json();
}

export async function testSource(cfg) {
  const r = await fetch("/api/sources/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  });
  if (!r.ok) throw new Error("測試失敗");
  return r.json();
}

export async function listDockerContainers() {
  const r = await fetch("/api/docker/containers");
  if (!r.ok) return { available: false, containers: [], reason: "請求失敗" };
  return r.json();
}

// ---- Web 搜尋設定 ----
export async function fetchWeb() {
  const r = await fetch("/api/web");
  if (!r.ok) throw new Error("無法取得 web 設定");
  return r.json();
}

export async function saveWeb(payload) {
  const r = await fetch("/api/web", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "儲存失敗");
  return r.json();
}

export async function testWeb() {
  const r = await fetch("/api/web/test", { method: "POST" });
  if (!r.ok) return { ok: false, detail: "請求失敗" };
  return r.json();
}

// ---- PNG Info：讀取圖片內嵌的生成參數 ----
export async function readPngInfo(image) {
  const r = await fetch("/api/png-info", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ image }),
  });
  if (!r.ok)
    throw new Error((await r.json().catch(() => ({}))).detail || "讀取失敗");
  return r.json();
}

// ---- 提示詞歷史（讀取 sd-webui-prompt-history 擴充的紀錄）----
export async function fetchPromptHistory(page = 1, q = "", pageSize = 24) {
  const params = new URLSearchParams({ page, q, page_size: pageSize });
  const r = await fetch(`/api/prompt-history?${params}`);
  if (!r.ok)
    throw new Error((await r.json().catch(() => ({}))).detail || "無法取得歷史");
  return r.json();
}

// 縮圖 URL（後端即時縮放並快取）
export const promptHistoryThumb = (id, size = 256) =>
  `/api/prompt-history/${encodeURIComponent(id)}/thumb?size=${size}`;

// 歷史資料目錄（env 當預設、UI 可覆寫）
export async function fetchPromptHistoryDir() {
  const r = await fetch("/api/prompt-history-dir");
  if (!r.ok) throw new Error("無法取得歷史目錄設定");
  return r.json();
}

export async function savePromptHistoryDir(dir) {
  const r = await fetch("/api/prompt-history-dir", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dir }),
  });
  if (!r.ok)
    throw new Error((await r.json().catch(() => ({}))).detail || "設定失敗");
  return r.json();
}

// ---- WAI 角色關鍵字搜尋 ----
export async function fetchCharacters(q = "", limit = 80) {
  const params = new URLSearchParams({ q, limit });
  const r = await fetch(`/api/booru-characters?${params}`);
  if (!r.ok) throw new Error("無法取得角色清單");
  return r.json();
}

// ---- 前端 UI 設定（後端持久化、跨裝置同步）----
export async function fetchUiSettings() {
  const r = await fetch("/api/ui-settings");
  if (!r.ok) throw new Error("無法取得設定");
  return r.json();
}

export async function saveUiSettings(settings) {
  const r = await fetch("/api/ui-settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
  if (!r.ok) throw new Error("儲存設定失敗");
  return r.json();
}

// ---- 對話紀錄（後端持久化、跨裝置）----
export async function listConversations() {
  const r = await fetch("/api/conversations");
  if (!r.ok) throw new Error("無法取得對話清單");
  return r.json();
}

export async function getConversation(id) {
  const r = await fetch(`/api/conversations/${encodeURIComponent(id)}`);
  if (!r.ok) throw new Error("無法取得對話");
  return r.json();
}

export async function putConversation(conv) {
  const r = await fetch(`/api/conversations/${encodeURIComponent(conv.id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(conv),
  });
  if (!r.ok) throw new Error("儲存對話失敗");
  return r.json();
}

export async function deleteConversationRemote(id) {
  const r = await fetch(`/api/conversations/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!r.ok) throw new Error("刪除對話失敗");
  return r.json();
}

export async function fetchHealth() {
  try {
    const r = await fetch("/api/health");
    return await r.json();
  } catch {
    return { ollama: false, a1111: false };
  }
}

// 手動 /image 後備
export async function generateImage(prompt, imageSettings) {
  const r = await fetch("/api/generate-image", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, image_settings: imageSettings }),
  });
  if (!r.ok) {
    const detail = await r.text();
    throw new Error(detail || "圖片生成失敗");
  }
  return r.json();
}

/**
 * 串流聊天。透過 fetch + ReadableStream 解析 SSE。
 * onEvent 會收到後端的每個事件物件。回傳 AbortController 供中斷。
 */
export async function compactConversation(model, messages, numCtx, engine = "ollama") {
  const r = await fetch("/api/compact", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model, messages, num_ctx: numCtx, engine }),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "壓縮失敗");
  return r.json();
}

export function streamChat(
  {
    model,
    messages,
    toolsEnabled,
    webEnabled,
    imageSettings,
    think,
    numCtx,
    imageSources,
    engine,
    effort,
  },
  onEvent,
  onDone,
  onError
) {
  const controller = new AbortController();

  (async () => {
    try {
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model,
          messages,
          tools_enabled: toolsEnabled,
          web_enabled: webEnabled,
          image_settings: imageSettings,
          think,
          num_ctx: numCtx,
          image_sources: imageSources,
          engine,
          effort,
        }),
        signal: controller.signal,
      });

      if (!resp.ok || !resp.body) {
        throw new Error(`伺服器錯誤 (${resp.status})`);
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // SSE 事件以空行分隔
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith("data:")) continue;
          const json = line.slice(5).trim();
          if (!json) continue;
          try {
            onEvent(JSON.parse(json));
          } catch {
            /* 略過解析失敗的片段 */
          }
        }
      }
      onDone?.();
    } catch (e) {
      if (e.name === "AbortError") {
        onDone?.();
      } else {
        onError?.(e);
      }
    }
  })();

  return controller;
}
