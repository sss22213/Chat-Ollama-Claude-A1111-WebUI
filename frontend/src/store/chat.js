import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import {
  fetchModels,
  fetchSdModels,
  fetchSamplers,
  fetchDefaults,
  fetchHealth,
  fetchEngines,
  streamChat,
  generateImage,
  compactConversation,
} from "../lib/api";

const uid = () =>
  (crypto.randomUUID && crypto.randomUUID()) ||
  Math.random().toString(36).slice(2);

const DEFAULT_IMAGE_SETTINGS = {
  steps: 28,
  cfg_scale: 5,
  width: 1024,
  height: 1024,
  sampler_name: "Euler a",
  seed: -1,
  sd_model_checkpoint: "",
  negative_prompt: "",
  denoising_strength: 0.6,
};

const stripPrefix = (dataUrl) =>
  dataUrl.includes(",") ? dataUrl.split(",")[1] : dataUrl;

// 串流時每個 token 都會觸發持久化；debounce 實際的 localStorage 寫入，
// 避免高頻同步寫入造成主執行緒卡頓與記憶體壓力。關閉分頁前會 flush。
const debouncedLocalStorage = (() => {
  let timer = null;
  let pending = null;
  const flush = () => {
    if (!pending) return;
    try {
      localStorage.setItem(pending[0], pending[1]);
    } catch (e) {
      /* QuotaExceeded 等：忽略，保住執行不中斷 */
    }
    pending = null;
  };
  if (typeof window !== "undefined") {
    window.addEventListener("beforeunload", flush);
  }
  return {
    getItem: (name) => localStorage.getItem(name),
    setItem: (name, value) => {
      pending = [name, value];
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        timer = null;
        flush();
      }, 800);
    },
    removeItem: (name) => localStorage.removeItem(name),
  };
})();

const newConversation = (model) => ({
  id: uid(),
  title: "新對話",
  model,
  messages: [],
});

export const useChat = create(
  persist(
    (set, get) => ({
      // ---- 持久化狀態 ----
      conversations: [],
      currentId: null,
      settings: {
        chatModel: "",
        engine: "ollama", // ollama | claude_cli
        toolsEnabled: true,
        webEnabled: false,
        think: false,
        numCtx: 8192,
        systemPrompt: "",
        lang: "zh-TW",
        imageSettings: { ...DEFAULT_IMAGE_SETTINGS },
      },

      // ---- 執行期狀態（不持久化）----
      models: [],
      sdModels: [],
      samplers: [],
      engines: { ollama: true, claude_cli: false },
      health: { ollama: true, a1111: true },
      streaming: false,
      _abort: null,
      attachments: [], // 待送出的附件圖 [{id, dataUrl}]
      usage: null, // {prompt_tokens, num_ctx} 上一輪 context 用量
      compacting: false,

      // ---- 附件（上傳/重繪共用）----
      // dataUrl：縮圖後（給預覽/vision/img2img、會持久化）；
      // original：未經縮圖的原圖（給 PNG Info 讀 metadata，僅 runtime、不持久化）。
      addAttachment(dataUrl, original) {
        set((st) => ({
          attachments: [
            ...st.attachments,
            { id: uid(), dataUrl, original: original || dataUrl },
          ],
        }));
      },
      removeAttachment(id) {
        set((st) => ({
          attachments: st.attachments.filter((a) => a.id !== id),
        }));
      },
      clearAttachments() {
        set({ attachments: [] });
      },

      // ---- 初始化：抓資源 ----
      async loadResources() {
        const engines = await fetchEngines().catch(() => ({
          ollama: true,
          claude_cli: false,
        }));
        // 持久化的引擎若已不可用（例如 claude 未掛載）→ 退回 ollama
        let engine = get().settings.engine || "ollama";
        if (engine === "claude_cli" && !engines.claude_cli) engine = "ollama";
        if (engine !== get().settings.engine) {
          set((st) => ({ settings: { ...st.settings, engine } }));
        }

        const [models, sdModels, samplers, defaults, health] =
          await Promise.all([
            fetchModels(engine).catch(() => []),
            fetchSdModels().catch(() => []),
            fetchSamplers().catch(() => []),
            fetchDefaults().catch(() => null),
            fetchHealth(),
          ]);

        set({ models, sdModels, samplers, health, engines });

        // 首次（或目前模型已不在清單中）：挑一個支援工具的模型當預設
        const s = get().settings;
        const valid = models.some((m) => m.name === s.chatModel);
        if ((!s.chatModel || !valid) && models.length) {
          const pref =
            models.find((m) => m.supports_tools)?.name || models[0].name;
          set({ settings: { ...get().settings, chatModel: pref } });
        }

        // 若沒有任何對話，建一個
        if (get().conversations.length === 0) {
          get().createConversation();
        } else if (!get().currentId) {
          set({ currentId: get().conversations[0].id });
        }
      },

      // 切換 AI 引擎（ollama / claude_cli）：重抓該引擎的模型清單並選預設
      async setEngine(engine) {
        if (engine === get().settings.engine) return;
        set((st) => ({
          settings: { ...st.settings, engine },
          usage: null,
        }));
        const models = await fetchModels(engine).catch(() => []);
        const pref =
          models.find((m) => m.supports_tools)?.name || models[0]?.name || "";
        set((st) => ({
          models,
          settings: { ...st.settings, chatModel: pref },
        }));
        // 同步目前對話的模型，讓下拉與送出都用該引擎的有效模型
        const cur = get().currentConversation();
        if (cur && pref) {
          useChat.setState((st) => ({
            conversations: st.conversations.map((c) =>
              c.id === st.currentId ? { ...c, model: pref } : c
            ),
          }));
        }
      },

      modelSupportsTools(name) {
        return !!get().models.find((m) => m.name === name)?.supports_tools;
      },

      // ---- 對話管理 ----
      createConversation() {
        const c = newConversation(get().settings.chatModel);
        set((st) => ({
          conversations: [c, ...st.conversations],
          currentId: c.id,
        }));
      },
      selectConversation(id) {
        set({ currentId: id });
      },
      deleteConversation(id) {
        set((st) => {
          const conversations = st.conversations.filter((c) => c.id !== id);
          let currentId = st.currentId;
          if (currentId === id) currentId = conversations[0]?.id || null;
          return { conversations, currentId };
        });
        if (get().conversations.length === 0) get().createConversation();
      },
      renameConversation(id, title) {
        set((st) => ({
          conversations: st.conversations.map((c) =>
            c.id === id ? { ...c, title } : c
          ),
        }));
      },

      // ---- 設定 ----
      setSettings(patch) {
        set((st) => ({ settings: { ...st.settings, ...patch } }));
      },
      setImageSettings(patch) {
        set((st) => ({
          settings: {
            ...st.settings,
            imageSettings: { ...st.settings.imageSettings, ...patch },
          },
        }));
      },

      // 內部：更新目前對話
      _updateCurrent(updater) {
        set((st) => ({
          conversations: st.conversations.map((c) =>
            c.id === st.currentId ? updater(c) : c
          ),
        }));
      },
      _patchMessage(msgId, patch) {
        get()._updateCurrent((c) => ({
          ...c,
          messages: c.messages.map((m) =>
            m.id === msgId
              ? { ...m, ...(typeof patch === "function" ? patch(m) : patch) }
              : m
          ),
        }));
      },

      currentConversation() {
        return get().conversations.find((c) => c.id === get().currentId) || null;
      },

      // ---- 送出訊息（核心）----
      async sendMessage(text) {
        const trimmed = text.trim();
        if (!trimmed || get().streaming) return;

        let convo = get().currentConversation();
        if (!convo) {
          get().createConversation();
          convo = get().currentConversation();
        }

        const { settings } = get();
        const model = convo.model || settings.chatModel;

        // /image 手動後備
        if (trimmed.startsWith("/image ")) {
          await get()._handleSlashImage(trimmed.slice(7).trim());
          return;
        }

        const attachments = get().attachments;
        const userMsg = {
          id: uid(),
          role: "user",
          content: trimmed,
          attachments: attachments.map((a) => ({ dataUrl: a.dataUrl })),
        };
        const assistantMsg = {
          id: uid(),
          role: "assistant",
          content: "",
          thinking: "",
          images: [],
          status: "streaming",
        };

        get()._updateCurrent((c) => ({
          ...c,
          // 首則訊息設為標題
          title: c.messages.length === 0 ? trimmed.slice(0, 30) : c.title,
          messages: [...c.messages, userMsg, assistantMsg],
        }));
        get().clearAttachments();

        // 組送出的訊息（帶 role+content；有附件則帶 images 供 vision/img2img）
        const history = get()
          .currentConversation()
          .messages.filter((m) => m.role === "user" || m.role === "assistant")
          .filter((m) => m.id !== assistantMsg.id)
          .map((m) => {
            const base = { role: m.role, content: m.content };
            if (m.attachments?.length) {
              base.images = m.attachments.map((a) => stripPrefix(a.dataUrl));
            }
            return base;
          });

        const apiMessages = settings.systemPrompt
          ? [{ role: "system", content: settings.systemPrompt }, ...history]
          : history;

        // 本回合附件的原圖（給 read_png_info 讀 metadata）；過大則略過避免請求肥大。
        const MAX_SRC = 9_000_000; // base64 字元數上限（約 6.7MB）
        const imageSources = attachments
          .map((a) => stripPrefix(a.original || a.dataUrl))
          .filter((b64) => b64.length <= MAX_SRC);

        set({ streaming: true });

        const canTools = get().modelSupportsTools(model);
        const toolsEnabled = settings.toolsEnabled && canTools;
        const webEnabled = settings.webEnabled && canTools;

        const abort = streamChat(
          {
            model,
            messages: apiMessages,
            toolsEnabled,
            webEnabled,
            imageSettings: settings.imageSettings,
            think: settings.think,
            numCtx: settings.numCtx,
            imageSources,
            engine: settings.engine,
          },
          (e) => {
            if (e.type === "thinking") {
              get()._patchMessage(assistantMsg.id, (m) => ({
                thinking: (m.thinking || "") + e.delta,
              }));
            } else if (e.type === "token") {
              get()._patchMessage(assistantMsg.id, (m) => ({
                content: (m.content || "") + e.delta,
                toolRunning: false, // 開始輸出答案代表工具階段結束
              }));
            } else if (e.type === "tool_call") {
              get()._patchMessage(assistantMsg.id, {
                toolRunning: true,
                toolName: e.name,
                progress: null,
              });
            } else if (e.type === "sources") {
              get()._patchMessage(assistantMsg.id, (m) => {
                const seen = new Set((m.sources || []).map((s) => s.url));
                const add = (e.results || []).filter(
                  (s) => s.url && !seen.has(s.url)
                );
                return {
                  toolRunning: false,
                  sources: [...(m.sources || []), ...add],
                };
              });
            } else if (e.type === "progress") {
              get()._patchMessage(assistantMsg.id, {
                progress: {
                  value: e.value || 0,
                  step: e.step,
                  steps: e.steps,
                  preview: e.preview
                    ? `data:image/png;base64,${e.preview}`
                    : null,
                },
              });
            } else if (e.type === "image") {
              get()._patchMessage(assistantMsg.id, (m) => ({
                toolRunning: false,
                progress: null,
                images: [...(m.images || []), { url: e.url, params: e.params }],
              }));
            } else if (e.type === "usage") {
              set({
                usage: {
                  prompt_tokens: e.prompt_tokens,
                  num_ctx: e.num_ctx || get().settings.numCtx,
                },
              });
            } else if (e.type === "error") {
              get()._patchMessage(assistantMsg.id, (m) => ({
                toolRunning: false,
                error: e.message,
              }));
            }
          },
          () => {
            get()._patchMessage(assistantMsg.id, {
              status: "done",
              toolRunning: false,
              progress: null,
            });
            set({ streaming: false, _abort: null });
          },
          (err) => {
            get()._patchMessage(assistantMsg.id, {
              status: "done",
              error: err.message,
              toolRunning: false,
              progress: null,
            });
            set({ streaming: false, _abort: null });
          }
        );

        set({ _abort: abort });
      },

      // /image 手動路徑
      async _handleSlashImage(prompt) {
        if (!prompt) return;
        const userMsg = {
          id: uid(),
          role: "user",
          content: `/image ${prompt}`,
        };
        const assistantMsg = {
          id: uid(),
          role: "assistant",
          content: "",
          images: [],
          status: "streaming",
          toolRunning: true,
        };
        get()._updateCurrent((c) => ({
          ...c,
          title: c.messages.length === 0 ? prompt.slice(0, 30) : c.title,
          messages: [...c.messages, userMsg, assistantMsg],
        }));
        set({ streaming: true });
        try {
          const result = await generateImage(
            prompt,
            get().settings.imageSettings
          );
          get()._patchMessage(assistantMsg.id, {
            toolRunning: false,
            status: "done",
            images: [{ url: result.url, params: result.params }],
          });
        } catch (e) {
          get()._patchMessage(assistantMsg.id, {
            toolRunning: false,
            status: "done",
            error: e.message,
          });
        } finally {
          set({ streaming: false });
        }
      },

      stopStreaming() {
        get()._abort?.abort();
        set({ streaming: false, _abort: null });
      },

      // 壓縮對話：把較舊訊息摘要成一則，保留最後一組往返，省 context
      async compact() {
        const convo = get().currentConversation();
        if (!convo || get().streaming || get().compacting) return;
        const turns = convo.messages.filter(
          (m) => m.role === "user" || m.role === "assistant"
        );
        if (turns.length < 3) return; // 太短不必壓縮
        const model = convo.model || get().settings.chatModel;
        const payload = turns.map((m) => ({ role: m.role, content: m.content }));

        set({ compacting: true });
        try {
          const { summary } = await compactConversation(
            model,
            payload,
            get().settings.numCtx,
            get().settings.engine
          );
          if (!summary) return;
          const keep = convo.messages.slice(-2); // 保留最後一組往返
          const summaryMsg = {
            id: uid(),
            role: "assistant",
            content: summary,
            compacted: true,
            status: "done",
          };
          get()._updateCurrent((c) => ({
            ...c,
            messages: [summaryMsg, ...keep],
          }));
          set({ usage: null });
        } catch (e) {
          /* 摘要失敗：保持原樣 */
        } finally {
          set({ compacting: false });
        }
      },
    }),
    {
      name: "webui-gen-image",
      storage: createJSONStorage(() => debouncedLocalStorage),
      partialize: (st) => ({
        conversations: st.conversations,
        currentId: st.currentId,
        settings: st.settings,
      }),
    }
  )
);
