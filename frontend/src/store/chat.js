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
  listConversations,
  getConversation,
  putConversation,
  deleteConversationRemote,
  fetchUiSettings,
  saveUiSettings,
  savePromptHistoryDir,
} from "../lib/api";

// engine / chatModel 是「裝置本機」設定，不跨裝置同步：
// 各裝置可用的引擎與模型不同，同步會導致某裝置切了引擎、其他裝置的模型清單也被換掉。
const DEVICE_LOCAL_SETTINGS = ["engine", "chatModel"];
function _syncableSettings(settings) {
  const out = { ...settings };
  for (const k of DEVICE_LOCAL_SETTINGS) delete out[k];
  return out;
}

// 設定變更後 debounce 寫回後端（跨裝置同步），避免每次微調都打一次。
let _settingsTimer = null;
function _debouncedSaveSettings(settings) {
  if (_settingsTimer) clearTimeout(_settingsTimer);
  _settingsTimer = setTimeout(() => {
    saveUiSettings(_syncableSettings(settings)).catch(() => {
      /* 後端不可用：保留本機，下次變更再試 */
    });
  }, 600);
}

// 一次性：把舊版（純前端）localStorage 裡的對話搬到後端。搬過就設旗標，避免重搬／復活已刪對話。
const MIGRATED_KEY = "webui-conv-migrated";
function readLocalConversations() {
  try {
    const raw = localStorage.getItem("webui-gen-image");
    return JSON.parse(raw || "{}")?.state?.conversations || [];
  } catch {
    return [];
  }
}

const uid = () =>
  (crypto.randomUUID && crypto.randomUUID()) ||
  Math.random().toString(36).slice(2);

// 推理強度（effort）各引擎獨立記憶；相容舊版（字串）→ 自動轉成各引擎共用該值
const EFFORT_DEFAULT = { claude_cli: "medium", codex: "medium", ollama: "medium" };
export function normEffort(e) {
  if (e && typeof e === "object") return { ...EFFORT_DEFAULT, ...e };
  const v = typeof e === "string" && e ? e : "medium";
  return { claude_cli: v, codex: v, ollama: v };
}
// 引擎 → effort 的鍵（codex/claude_cli 用引擎名；ollama 共用一個，僅 gpt-oss 會用到）
export const effortKeyFor = (engine) => (engine === "ollama" ? "ollama" : engine);

// 把一張圖的參數整理成 A1111 風格 geninfo 文字（info 缺時的後備）
function paramsToText(p) {
  if (!p) return "";
  const lines = [];
  if (p.prompt) lines.push(p.prompt);
  if (p.negative_prompt) lines.push(`Negative prompt: ${p.negative_prompt}`);
  const tail = [];
  if (p.steps != null) tail.push(`Steps: ${p.steps}`);
  if (p.sampler_name) tail.push(`Sampler: ${p.sampler_name}`);
  if (p.cfg_scale != null) tail.push(`CFG scale: ${p.cfg_scale}`);
  if (p.seed != null) tail.push(`Seed: ${p.seed}`);
  if (p.width && p.height) tail.push(`Size: ${p.width}x${p.height}`);
  if (p.sd_model_checkpoint) tail.push(`Model: ${p.sd_model_checkpoint}`);
  if (tail.length) lines.push(tail.join(", "));
  return lines.join("\n");
}

// 把一則訊息已生成的圖片參數，整理成「隱藏」文字附在送出的 content 後面，
// 讓模型之後被問到「剛剛那張圖的 PNG info / 參數」時答得出來（畫面不顯示）。
export function genInfoForModel(images) {
  if (!images?.length) return "";
  const blocks = images
    .map((im, i) => {
      const txt = (im.info && im.info.trim()) || paramsToText(im.params);
      if (!txt) return "";
      const tag = images.length > 1 ? ` #${i + 1}` : "";
      return `已生成圖片${tag} 的參數 (PNG info)：\n${txt}`;
    })
    .filter(Boolean);
  return blocks.length
    ? `\n\n[系統備註，使用者看不到，供你回答生成參數用]\n${blocks.join("\n\n")}`
    : "";
}

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
  messages: [], // messages 為陣列 = 已載入；summary（未載入）時為 undefined
  created_at: Date.now() / 1000,
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
        effort: { ...EFFORT_DEFAULT }, // 推理強度，各引擎獨立
        numCtx: 8192,
        systemPrompt: "",
        lang: "zh-TW",
        imageSettings: { ...DEFAULT_IMAGE_SETTINGS },
      },

      // ---- 執行期狀態（不持久化）----
      models: [],
      sdModels: [],
      samplers: [],
      engines: { ollama: true, claude_cli: false, codex: false },
      features: { promptHistory: false }, // 後端可用的選用功能（依掛載/設定而定）
      health: { ollama: true, a1111: true },
      streaming: false,
      _abort: null,
      attachments: [], // 待送出的附件圖 [{id, dataUrl}]
      usage: null, // {prompt_tokens, num_ctx} 上一輪 context 用量
      compacting: false,
      composerDraft: null, // 要塞進輸入框的草稿（如「套用歷史」帶入 prompt）

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
        // 先套用後端保存的 UI 設定（跨裝置同步）；localStorage 仍當首屏快取
        let serverSettings = null;
        try {
          serverSettings = await fetchUiSettings();
        } catch {
          serverSettings = null;
        }
        const hadServerSettings =
          serverSettings && Object.keys(serverSettings).length > 0;
        if (hadServerSettings) {
          // 套用後端設定，但忽略 engine / chatModel（裝置本機，避免引擎被其他裝置帶歪）
          const incoming = _syncableSettings(serverSettings);
          set((st) => ({
            settings: {
              ...st.settings,
              ...incoming,
              imageSettings: {
                ...st.settings.imageSettings,
                ...(incoming.imageSettings || {}),
              },
            },
          }));
        }

        const engines = await fetchEngines().catch(() => ({
          ollama: true,
          claude_cli: false,
          codex: false,
        }));
        // 持久化的引擎若已不可用（例如 claude/codex 未掛載）→ 退回 ollama
        let engine = get().settings.engine || "ollama";
        if (engine !== "ollama" && !engines[engine]) engine = "ollama";
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

        set({
          models,
          sdModels,
          samplers,
          health,
          engines,
          features: { promptHistory: !!defaults?.prompt_history },
        });

        // 首次（或目前模型已不在清單中）：挑一個支援工具的模型當預設
        const s = get().settings;
        const valid = models.some((m) => m.name === s.chatModel);
        if ((!s.chatModel || !valid) && models.length) {
          const pref =
            models.find((m) => m.supports_tools)?.name || models[0].name;
          set({ settings: { ...get().settings, chatModel: pref } });
        }

        // 後端尚無設定 → 用本機現有設定種子化（不含 engine/chatModel）
        if (!hadServerSettings) {
          saveUiSettings(_syncableSettings(get().settings)).catch(() => {});
        }

        // 對話改由後端載入（跨裝置、長期保存）
        await get().loadConversations();
      },

      // 從後端載入對話摘要清單（messages 採懶載入：點開才抓）
      async loadConversations() {
        let summaries = null;
        try {
          summaries = await listConversations();
        } catch {
          summaries = null; // 後端連不上
        }

        // 後端連不上：保留現有（可能來自舊 localStorage rehydrate 的）對話，不動作
        if (summaries === null) {
          if (get().conversations.length === 0) get().createConversation();
          return;
        }

        // 一次性遷移：後端是空的、且本機有舊對話 → 上傳
        if (summaries.length === 0 && !localStorage.getItem(MIGRATED_KEY)) {
          // 來源：原始 localStorage；若已被覆寫則退回 rehydrate 進記憶體的舊對話
          const raw = readLocalConversations();
          const source = raw.length ? raw : get().conversations;
          const toMigrate = source.filter((c) => (c.messages?.length || 0) > 0);
          for (const c of toMigrate) {
            try {
              await putConversation(c);
            } catch {
              /* 個別失敗略過 */
            }
          }
          if (toMigrate.length) summaries = await listConversations().catch(() => []);
        }
        localStorage.setItem(MIGRATED_KEY, "1");

        // summary → 對話物件（messages: undefined 代表尚未載入）
        const conversations = summaries.map((sm) => ({
          ...sm,
          messages: undefined,
        }));
        let currentId = get().currentId;
        if (!conversations.some((c) => c.id === currentId)) {
          currentId = conversations[0]?.id || null;
        }
        set({ conversations, currentId });

        if (conversations.length === 0) {
          get().createConversation();
        } else if (currentId) {
          get()._ensureLoaded(currentId);
        }
      },

      // 確保某對話的 messages 已從後端載入（messages 為陣列即視為已載入）
      async _ensureLoaded(id) {
        const c = get().conversations.find((x) => x.id === id);
        if (!c || Array.isArray(c.messages)) return;
        try {
          const full = await getConversation(id);
          set((st) => ({
            conversations: st.conversations.map((x) =>
              x.id === id ? { ...x, ...full, messages: full.messages || [] } : x
            ),
          }));
        } catch {
          // 載入失敗：標記為空陣列避免無限重試
          set((st) => ({
            conversations: st.conversations.map((x) =>
              x.id === id ? { ...x, messages: [] } : x
            ),
          }));
        }
      },

      // 把某對話（需已載入且有內容）寫回後端
      _syncConversation(id) {
        const c = get().conversations.find((x) => x.id === id);
        if (!c || !Array.isArray(c.messages) || c.messages.length === 0) return;
        putConversation(c).catch(() => {
          /* 同步失敗：下次互動會再試 */
        });
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
          get()._syncConversation(get().currentId);
        }
        _debouncedSaveSettings(get().settings); // 同步 engine + chatModel 到後端
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
        get()._ensureLoaded(id); // 懶載入該對話的訊息
      },
      deleteConversation(id) {
        set((st) => {
          const conversations = st.conversations.filter((c) => c.id !== id);
          let currentId = st.currentId;
          if (currentId === id) currentId = conversations[0]?.id || null;
          return { conversations, currentId };
        });
        deleteConversationRemote(id).catch(() => {});
        if (get().conversations.length === 0) get().createConversation();
        else get()._ensureLoaded(get().currentId);
      },
      renameConversation(id, title) {
        set((st) => ({
          conversations: st.conversations.map((c) =>
            c.id === id ? { ...c, title } : c
          ),
        }));
        get()._syncConversation(id);
      },

      // ---- 設定 ----（本機即時更新 + debounce 同步到後端）
      setSettings(patch) {
        set((st) => ({ settings: { ...st.settings, ...patch } }));
        _debouncedSaveSettings(get().settings);
      },
      setImageSettings(patch) {
        set((st) => ({
          settings: {
            ...st.settings,
            imageSettings: { ...st.settings.imageSettings, ...patch },
          },
        }));
        _debouncedSaveSettings(get().settings);
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
        // 確保訊息已從後端載入後再附加（避免 messages 為 undefined）
        await get()._ensureLoaded(convo.id);
        convo = get().currentConversation();
        const convId = convo.id;

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
            // 助理曾生成的圖片，把其 PNG info 以隱藏文字附在 content（畫面不變，只給模型看）
            if (m.role === "assistant" && m.images?.length) {
              base.content = (m.content || "") + genInfoForModel(m.images);
            }
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
        // 取當前引擎自己的 effort
        const effort = normEffort(settings.effort)[effortKeyFor(settings.engine)];

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
            effort,
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
                images: [
                  ...(m.images || []),
                  { url: e.url, params: e.params, info: e.info || "" },
                ],
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
            get()._syncConversation(convId); // 保存到後端（跨裝置）
          },
          (err) => {
            get()._patchMessage(assistantMsg.id, {
              status: "done",
              error: err.message,
              toolRunning: false,
              progress: null,
            });
            set({ streaming: false, _abort: null });
            get()._syncConversation(convId);
          }
        );

        set({ _abort: abort });
      },

      // /image 手動路徑（settingsOverride：歷史「直接生成」時帶入該筆自己的參數）
      async _handleSlashImage(prompt, settingsOverride = null) {
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
            settingsOverride || get().settings.imageSettings
          );
          get()._patchMessage(assistantMsg.id, {
            toolRunning: false,
            status: "done",
            images: [
              { url: result.url, params: result.params, info: result.info || "" },
            ],
          });
        } catch (e) {
          get()._patchMessage(assistantMsg.id, {
            toolRunning: false,
            status: "done",
            error: e.message,
          });
        } finally {
          set({ streaming: false });
          get()._syncConversation(get().currentId);
        }
      },

      // ---- 提示詞歷史（sd-webui-prompt-history 整合）----
      // 把要塞進輸入框的草稿交給 Composer 取用（取用後 Composer 會清回 null）
      setComposerDraft(text) {
        set({ composerDraft: text });
      },

      // checkpoint 對不上目前 A1111 已載入的清單時就拿掉，避免生成報錯／下拉變空
      _historySettings(record, mergeCurrent) {
        const base = mergeCurrent ? { ...get().settings.imageSettings } : {};
        const s = { ...base, ...(record.settings || {}) };
        const sdModels = get().sdModels;
        if (
          s.sd_model_checkpoint &&
          !sdModels.find((m) => m.model_name === s.sd_model_checkpoint)
        ) {
          delete s.sd_model_checkpoint;
        }
        return s;
      },

      // 設定歷史資料目錄（空字串＝回到 env 預設）；同步更新「歷史」按鈕的顯示
      async setPromptHistoryDir(dir) {
        const info = await savePromptHistoryDir(dir);
        set((st) => ({
          features: { ...st.features, promptHistory: !!info.available },
        }));
        return info;
      },

      // 套用到設定：套用該筆參數 + 把 prompt 以 /image 帶入輸入框（檢查／編輯後可直接生成）
      applyHistory(record) {
        get().setImageSettings(get()._historySettings(record, false));
        get().setComposerDraft(record.prompt ? `/image ${record.prompt}` : "");
      },

      // 角色快速生成：用「角色 tag + 畫質詞」直接生成一張（WAI/Illustrious 友善）
      // 角色可為字串 tag 或物件 {tag, prompt}；有完整提示詞（Drawing Spells）就優先用，生成更準
      async generateCharacter(c) {
        const tag = typeof c === "string" ? c : c?.tag;
        const full = typeof c === "object" ? (c?.prompt || "").trim() : "";
        if (get().streaming || !tag) return;
        let convo = get().currentConversation();
        if (!convo) {
          get().createConversation();
          convo = get().currentConversation();
        }
        await get()._ensureLoaded(convo.id);
        const body = full || tag;
        const prompt = `${body}, masterpiece, best quality, amazing quality`;
        await get()._handleSlashImage(prompt, get().settings.imageSettings);
      },

      // 直接生成：用該筆自己的 prompt + 參數立刻重生一張（不改動目前的生成設定）
      async generateFromHistory(record) {
        if (get().streaming || !record.prompt) return;
        let convo = get().currentConversation();
        if (!convo) {
          get().createConversation();
          convo = get().currentConversation();
        }
        await get()._ensureLoaded(convo.id);
        await get()._handleSlashImage(
          record.prompt,
          get()._historySettings(record, true)
        );
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
          get()._syncConversation(get().currentId);
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
      // 對話改存後端（跨裝置、長期保存）；localStorage 只留裝置本機偏好。
      partialize: (st) => ({
        currentId: st.currentId,
        settings: st.settings,
      }),
    }
  )
);
