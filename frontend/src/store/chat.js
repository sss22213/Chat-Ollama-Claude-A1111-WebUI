import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import {
  fetchModels,
  reloadOllamaModel,
  fetchSdModels,
  fetchSamplers,
  fetchDefaults,
  fetchHealth,
  fetchEngines,
  streamChat,
  followChatRun,
  getChatRun,
  cancelChatRun,
  generateImage,
  compactConversation,
  listConversations,
  getConversation,
  putConversation,
  deleteConversationRemote,
  fetchUiSettings,
  saveUiSettings,
  savePromptHistoryDir,
  fetchSkills,
} from "../lib/api";
import { fetchWorkflows, imagesIn, outputText, runWorkflow } from "../lib/workflowApi";

// engine / chatModel 是「裝置本機」設定，不跨裝置同步：
// 各裝置可用的引擎與模型不同，同步會導致某裝置切了引擎、其他裝置的模型清單也被換掉。
const DEVICE_LOCAL_SETTINGS = ["engine", "chatModel"];
// 技能選擇：settings.skills 陣列（相容舊版單一字串 settings.skill）
export function skillSelection(settings) {
  if (Array.isArray(settings?.skills)) return settings.skills;
  const legacy = settings?.skill || "";
  return legacy ? legacy.split(",").map((x) => x.trim()).filter(Boolean) : [];
}
// 送給後端的參數："__auto__" / "a,b" / ""
export function skillParam(settings) {
  const sel = skillSelection(settings);
  return sel.includes("__auto__") ? "__auto__" : sel.join(",");
}
// 依後端技能清單整理選擇：__auto__ 保留、已被移除的技能剔除；回 null 表示不用改
function _normalizedSkills(settings, list) {
  const sel = skillSelection(settings);
  const next = sel.includes("__auto__")
    ? ["__auto__"]
    : sel.filter((slug) => list.some((s) => s.slug === slug));
  const same =
    Array.isArray(settings.skills) &&
    !("skill" in settings) &&
    next.length === settings.skills.length &&
    next.every((x, i) => x === settings.skills[i]);
  return same ? null : next;
}

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
const EFFORT_DEFAULT = { claude_cli: "medium", codex: "medium", ollama: "medium", strata: "medium" };
export function normEffort(e) {
  if (e && typeof e === "object") return { ...EFFORT_DEFAULT, ...e };
  const v = typeof e === "string" && e ? e : "medium";
  return { ...EFFORT_DEFAULT, claude_cli: v, codex: v, ollama: v };
}
// 引擎 → effort 的鍵（codex/claude_cli/strata 用引擎名；ollama 共用一個，僅 gpt-oss 會用到）
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
// 注意：只會附在「最後一則」有圖的助理訊息（見 send 的歷史組裝）——每則都附會讓
// 歷史充滿 prompt/negative 純文字範本，誘導模型模仿著印文字而不呼叫工具，
// 也是退化重複迴圈的素材來源。可在設定用 sendGenInfo 整個關閉。
// 模型偶爾會把給它看的「系統備註」原樣抄進回覆；從標記起到結尾一律切掉（顯示、保存、再送回模型都用）
const NOTE_MARKER = "[系統備註，使用者看不到";
export function stripEchoedNote(text) {
  if (typeof text !== "string") return text;
  const i = text.indexOf(NOTE_MARKER);
  return i < 0 ? text : text.slice(0, i).trimEnd();
}

// 對話裡的圖依序編號（跟後端 chat.conversation_images 一樣：使用者附的圖、助理訊息裡 /images/ 的圖）。
// 回 Map：訊息 id → 每張圖的編號（user 對 attachments、assistant 對 images；沒編號的是 null）。
export function imageNumbers(messages) {
  const out = new Map();
  let n = 0;
  for (const m of messages || []) {
    if (m.role === "user") {
      out.set(m.id, (m.attachments || []).map(() => ++n));
    } else if (m.role === "assistant") {
      out.set(
        m.id,
        (m.images || []).map((im) => (typeof im?.url === "string" && im.url.startsWith("/images/") ? ++n : null))
      );
    }
  }
  return out;
}

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
    ? "\n\n[系統備註，使用者看不到，供你回答生成參數用。Reference data only — " +
        "NEVER imitate this format or print prompt tags as plain text in your " +
        "replies; to create a new image you must still call the image tool / " +
        `marker as instructed.]\n${blocks.join("\n\n")}`
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

// 存檔排隊：同一則對話一次只送一個 PUT（自己的兩個存檔才不會互相當成舊版本）。值＝最後一個存檔的 promise
const _saving = new Map();
// 還沒存到後端的訊息 id（/image、/workflow 進行中；送出時問題還沒存好）：存檔衝突、本機換成後端最新版時
// 這些訊息留本機的，不會因為後端還沒有就不見
const _unsaved = new Set();
// 這個分頁自己刪掉的對話：之後排隊中的存檔不送，也不會被當成「別處刪除」提示
const _deleted = new Set();

// ---- 對話的變更（_syncConversation 的 redo）：本機與後端最新版都用同一個函式改，重複套用結果不變 ----
// 把訊息放進對話：同 id 的換掉、沒有的接在最後；對話裡只有這些訊息（新對話）時用 title 當標題
function withMessages(c, msgs, title) {
  const list = Array.isArray(c.messages) ? c.messages : [];
  const byId = new Map(msgs.map((m) => [m.id, m]));
  const messages = list.map((m) => byId.get(m.id) || m);
  for (const m of msgs) if (!list.some((x) => x.id === m.id)) messages.push(m);
  const fresh = title && list.every((m) => byId.has(m.id));
  return { ...c, title: fresh ? title : c.title, messages };
}
// 改一則訊息：patch 可以是函式（回 null＝不用改）；訊息不在、或不用改都回 null
function withMessagePatch(c, msgId, patch) {
  const m = (c.messages || []).find((x) => x.id === msgId);
  const p = m && (typeof patch === "function" ? patch(m) : patch);
  if (!p) return null;
  return { ...c, messages: c.messages.map((x) => (x.id === msgId ? { ...x, ...p } : x)) };
}

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
        sendGenInfo: true, // 把最近一張生成圖的參數（PNG info）提供給模型
        sendKey: "enter", // 送出按鍵：enter（Enter 送出、Shift+Enter 換行）| shiftEnter（相反）
        autoCompact: false, // 回覆結束後 context 用量達門檻就自動壓縮對話
        autoCompactAt: 0.8, // 門檻（用量 / num_ctx）
        think: false,
        effort: { ...EFFORT_DEFAULT }, // 推理強度，各引擎獨立
        numCtx: 8192,
        systemPrompt: "",
        lang: "zh-TW",
        // 啟用的技能 slug 清單（Agent Skill）；可多選；["__auto__"]＝模型自選；空＝不啟用
        // （舊版單一字串 settings.skill 會在啟動時自動轉成這個陣列）
        skills: [],
        imageSettings: { ...DEFAULT_IMAGE_SETTINGS },
      },

      // ---- 執行期狀態（不持久化）----
      models: [],
      sdModels: [],
      samplers: [],
      engines: { ollama: true, claude_cli: false, codex: false, strata: false },
      features: { promptHistory: false }, // 後端可用的選用功能（依掛載/設定而定）
      skills: [], // 後端掃到的技能清單 [{slug,name,description,...}]
      health: { ollama: true, a1111: true },
      streaming: false,
      _abort: null,
      _run: null, // 正在看的後端回覆 {convId, msgId}（回覆在後端跑，這裡只是接著看）
      _resuming: null, // 正在確認哪個對話的回覆還在不在跑
      _convosLoaded: false, // 已從後端載過對話清單（之後才做跨裝置刷新）
      _lastRefresh: 0,
      attachments: [], // 待送出的附件圖 [{id, dataUrl}]
      usage: null, // {prompt_tokens, num_ctx} 上一輪 context 用量
      compacting: null, // 正在壓縮的對話 id
      syncNotice: null, // 存檔沒存成功的提示 {kind: deleted（別處刪了）| failed, title}（顯示在輸入框上方）
      modelReload: null, // 模型重新載入的狀態 {status: busy|done|error, ...}
      composerDraft: null, // 要塞進輸入框的草稿（如「套用歷史」帶入 prompt，會「取代」輸入框內容）
      composerInsert: null, // 要「附加」到輸入框的片段（如 LoRA 瀏覽器帶入 tag，保留已輸入內容）

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
          strata: false,
        }));
        // 持久化的引擎若已不可用（例如 claude/codex 未掛載、Strata 沒開）→ 退回 ollama
        let engine = get().settings.engine || "ollama";
        if (engine !== "ollama" && !engines[engine]) engine = "ollama";
        if (engine !== get().settings.engine) {
          set((st) => ({ settings: { ...st.settings, engine } }));
        }

        const [models, sdModels, samplers, defaults, health, skills] =
          await Promise.all([
            fetchModels(engine).catch(() => []),
            fetchSdModels().catch(() => []),
            fetchSamplers().catch(() => []),
            fetchDefaults().catch(() => null),
            fetchHealth(),
            fetchSkills(),
          ]);

        // 啟用中的技能若已不在清單（被移除）→ 剔除；「自動」與其餘選擇保留（含舊版字串轉陣列）
        {
          const next = _normalizedSkills(get().settings, skills);
          if (next) {
            set((st) => {
              const { skill: _legacy, ...rest } = st.settings;
              return { settings: { ...rest, skills: next } };
            });
          }
        }

        set({
          models,
          sdModels,
          samplers,
          health,
          engines,
          skills,
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

      // 重抓技能清單（新增/編輯/刪除後刷新）；啟用中技能若被刪則剔除
      async reloadSkills() {
        const skills = await fetchSkills();
        set((st) => {
          const next = _normalizedSkills(st.settings, skills);
          if (!next) return { skills };
          const { skill: _legacy, ...rest } = st.settings;
          return { skills, settings: { ...rest, skills: next } };
        });
        return skills;
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
              await putConversation(c, null); // 只建新的，不蓋掉後端已有的
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
        set({ conversations, currentId, _convosLoaded: true, _lastRefresh: Date.now() });

        if (conversations.length === 0) {
          get().createConversation();
        } else if (currentId) {
          get()._ensureLoaded(currentId);
        }
      },

      // 跨裝置同步：重抓後端摘要清單並合併到本機狀態。
      // - 後端較新的對話（updated_at 比本機大）丟掉本機快取的 messages，下次顯示時重新載入
      // - 後端已刪的對話移除；尚未存到後端的新對話（本機才有）保留在最上面
      // - 串流 / 壓縮中不做，避免覆蓋進行中的對話
      async refreshConversations() {
        if (!get()._convosLoaded || get().streaming || get().compacting) return false;
        let summaries;
        try {
          summaries = await listConversations();
        } catch {
          return false; // 後端連不上：維持現狀
        }
        set({ _lastRefresh: Date.now() });
        const local = get().conversations;
        const localById = new Map(local.map((c) => [c.id, c]));
        const serverIds = new Set(summaries.map((sm) => sm.id));
        const merged = summaries.map((sm) => {
          const loc = localById.get(sm.id);
          if (!loc) return { ...sm, messages: undefined };
          const stale =
            Array.isArray(loc.messages) &&
            (sm.updated_at || 0) > (loc.updated_at || 0) + 1e-6;
          return stale
            ? { ...loc, ...sm, messages: undefined }
            : { ...loc, title: sm.title ?? loc.title, updated_at: sm.updated_at };
        });
        // 本機才有：還沒同步過（沒有 updated_at）的對話保留；曾在後端、現在不見＝別的裝置刪了
        const localOnly = local.filter((c) => !serverIds.has(c.id) && !c.updated_at);
        const conversations = [...localOnly, ...merged];
        let currentId = get().currentId;
        if (!conversations.some((c) => c.id === currentId)) {
          currentId = conversations[0]?.id || null;
        }
        set({ conversations, currentId });
        if (conversations.length === 0) get().createConversation();
        else if (currentId) {
          get()._ensureLoaded(currentId);
          get()._resumeRun(currentId);
        }
        return true;
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
          if (id === get().currentId) get()._resumeRun(id);
        } catch {
          // 載入失敗：標記為空陣列避免無限重試
          set((st) => ({
            conversations: st.conversations.map((x) =>
              x.id === id ? { ...x, messages: [] } : x
            ),
          }));
        }
      },

      // 把某對話（需已載入且有內容）寫回後端，帶上本機上次看到的版本（updated_at）。
      // redo：這次改了什麼（對話 → 改好的對話；不用改回 null），要能重複套用。後端在那之後被改過
      // （別的分頁 / 裝置、或後端回覆存了新內容）會回 409 附最新版：在最新版上用 redo 重做一次再存，
      // 本機的舊資料不會蓋掉沒看過的訊息。對話已在別處刪除就不建回來（本機也拿掉並提示）。
      // 同一則對話的存檔排隊、一次一個。回 null＝存好了（或不用存），失敗回 Error；不會 reject，不等結果也可以
      _syncConversation(id, redo) {
        const run = () => get()._putConversation(id, redo);
        const p = (_saving.get(id) || Promise.resolve()).then(run, run);
        _saving.set(id, p);
        p.then(() => {
          if (_saving.get(id) === p) _saving.delete(id);
        });
        return p;
      },

      async _putConversation(id, redo) {
        const c = get().conversations.find((x) => x.id === id);
        if (_deleted.has(id) || !c || !Array.isArray(c.messages) || c.messages.length === 0) return null;
        let body = (redo && redo(c)) || c;
        let base = c.updated_at ?? null;
        for (let i = 0; i < 4; i++) {
          if (!get().conversations.some((x) => x.id === id)) return null; // 存的途中在這裡刪掉了
          try {
            const stored = await putConversation(body, base);
            get()._adoptServer(id, stored); // 記下後端版本，refreshConversations 與下次存檔才知道看過哪一版
            return null;
          } catch (e) {
            if (e.status !== 409) return e; // 連不上等：本機留著，下次存檔會一起帶上
            if (!e.current) {
              get()._dropConversation(id);
              return e;
            }
            const next = redo && redo(e.current);
            if (!next) {
              get()._adoptServer(id, e.current); // 最新版已經是這樣，不用再存
              return null;
            }
            body = next;
            base = e.current.updated_at ?? null;
          }
        }
        set({ syncNotice: { kind: "failed", title: c.title } });
        return new Error("對話在別處一直有更新，沒有存成功");
      },

      // 本機換成後端存好的版本。本機比後端新的訊息留本機的：正在看的回覆（後端每 3 秒才存一次）、
      // 還沒存的（/image、/workflow 進行中）
      _adoptServer(id, stored) {
        const run = get()._run;
        const mine = (mid) => (run?.convId === id && run.msgId === mid) || _unsaved.has(mid);
        set((st) => ({
          conversations: st.conversations.map((c) => {
            if (c.id !== id) return c;
            const local = new Map((c.messages || []).map((m) => [m.id, m]));
            const messages = (stored.messages || []).map((m) =>
              mine(m.id) && local.has(m.id) ? local.get(m.id) : m
            );
            const have = new Set(messages.map((m) => m.id));
            for (const m of c.messages || []) if (mine(m.id) && !have.has(m.id)) messages.push(m);
            return { ...c, ...stored, messages };
          }),
        }));
      },

      // 對話已在別的分頁 / 裝置刪除：本機也拿掉（不建回來），提示剛才的變更沒存
      _dropConversation(id) {
        const gone = get().conversations.find((c) => c.id === id);
        if (!gone) return;
        set((st) => {
          const conversations = st.conversations.filter((c) => c.id !== id);
          const currentId = st.currentId === id ? conversations[0]?.id || null : st.currentId;
          return { conversations, currentId, syncNotice: { kind: "deleted", title: gone.title } };
        });
        if (get().conversations.length === 0) get().createConversation();
        else get()._ensureLoaded(get().currentId);
      },

      // 後端回覆存了一次（prev → next）：本機的版本就是 prev 的話，新版本的內容本機都有了（存檔前的事件
      // 都收到了），跟著換成 next；之後整則存檔（換模型等）才不會被當成舊版本
      _advanceBase(id, prev, next) {
        if (prev == null || next == null) return;
        set((st) => ({
          conversations: st.conversations.map((c) =>
            c.id === id && c.updated_at === prev ? { ...c, updated_at: next } : c
          ),
        }));
      },

      // 改一則對話（本機馬上改）並存回後端；redo 見 _syncConversation
      _editConversation(id, redo) {
        set((st) => ({
          conversations: st.conversations.map((c) => (c.id === id ? redo(c) || c : c)),
        }));
        return get()._syncConversation(id, redo);
      },

      // 重新整理 Ollama 模型清單，再把目前模型從記憶體卸載後重新載入
      //（ollama create / pull / rm 之後不用重整網頁；覆蓋同名模型後也會換成新版本）
      async reloadModel(model) {
        const st = get();
        if (st.settings.engine !== "ollama" || st.modelReload?.status === "busy") return;
        // 串流/壓縮中卸載模型會打斷那次請求
        if (st.streaming || st.compacting) return;
        set({ modelReload: { status: "busy", model } });
        try {
          const models = await fetchModels("ollama", true);
          set({ models });
          if (!models.some((m) => m.name === model)) {
            set({ modelReload: { status: "error", code: "gone", model } });
            return;
          }
          const info = await reloadOllamaModel(model, get().settings.numCtx);
          set({ modelReload: { status: "done", ...info } });
        } catch (e) {
          set({ modelReload: { status: "error", message: e.message, model } });
        }
      },

      // 切換 AI 引擎（ollama / claude_cli / codex / strata）：重抓該引擎的模型清單並選預設
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
          get()._editConversation(cur.id, (c) => (c.model === pref ? null : { ...c, model: pref }));
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
        get()._resumeRun(id); // 已載入過的對話：回覆可能還在跑
      },
      deleteConversation(id) {
        _deleted.add(id);
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
        get()._editConversation(id, (c) => (c.title === title ? null : { ...c, title }));
      },
      // 換目前對話的模型（頂端的模型下拉）：存回後端，存檔衝突時在最新版上重新套用
      setConversationModel(name) {
        const id = get().currentId;
        if (id) get()._editConversation(id, (c) => (c.model === name ? null : { ...c, model: name }));
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

      // 內部：更新指定對話（一律用 id，不用「目前對話」：非同步回來時使用者可能已經切走）
      _updateConversation(id, patch) {
        set((st) => ({ conversations: st.conversations.map((c) => (c.id === id ? { ...c, ...patch } : c)) }));
      },

      // 改指定對話的訊息：回覆跑到一半切去別的對話，也要改到原本那則
      _patchMessageIn(convId, msgId, patch) {
        set((st) => ({
          conversations: st.conversations.map((c) =>
            c.id === convId && Array.isArray(c.messages)
              ? {
                  ...c,
                  messages: c.messages.map((m) =>
                    m.id === msgId ? { ...m, ...(typeof patch === "function" ? patch(m) : patch) } : m
                  ),
                }
              : c
          ),
        }));
      },

      currentConversation() {
        return get().conversations.find((c) => c.id === get().currentId) || null;
      },

      // 一個事件 → 助理訊息。規則要跟後端 chat_runs.ChatRun.apply 一致（那邊負責存檔，這裡負責即時顯示）
      _applyChatEvent(convId, msgId, e) {
        const patch = (p) => get()._patchMessageIn(convId, msgId, p);
        if (e.type === "thinking") {
          patch((m) => ({
            thinking: (m.thinking || "") + e.delta,
          }));
        } else if (e.type === "token") {
          patch((m) => ({
            content: (m.content || "") + e.delta,
            toolRunning: false, // 開始輸出答案代表工具階段結束
          }));
        } else if (e.type === "tool_call") {
          patch({
            toolRunning: true,
            toolName: e.name,
            progress: null,
          });
        } else if (e.type === "lora_renamed") {
          // LoRA 改名了：開著的漫畫作品裡的 <lora:舊名:…> 也換掉（伺服器上的作品後端已經換好）
          import("./comic").then((m) => m.useComic.getState().replaceLoraNames(e.mapping || {}));
        } else if (e.type === "gallery") {
          // 技能工具回傳的圖庫（如 Civitai Helper 的本地範例圖＋提示詞）
          patch((m) => ({
            galleries: [
              ...(m.galleries || []),
              { title: e.title || "", trained_words: e.trained_words || [], items: e.items || [] },
            ],
          }));
        } else if (e.type === "candidates") {
          // 技能工具回傳的候選清單（如 civitai 搜尋結果卡片）
          patch((m) => ({
            candidates: [
              ...(m.candidates || []),
              { kind: e.kind, items: e.items || [], next_cursor: e.next_cursor || null },
            ],
          }));
        } else if (e.type === "sources") {
          patch((m) => {
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
          patch({
            progress: {
              value: e.value || 0,
              text: e.text || "",
              step: e.step,
              steps: e.steps,
              preview: e.preview
                ? `data:image/png;base64,${e.preview}`
                : null,
            },
          });
        } else if (e.type === "image") {
          patch((m) => ({
            toolRunning: false,
            progress: null,
            images: [
              ...(m.images || []),
              // at：圖出現時已輸出的文字長度；訊息依此把圖插在當時那段文字下面
              { url: e.url, params: e.params, info: e.info || "", at: (m.content || "").length },
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
          patch((m) => ({
            toolRunning: false,
            error: e.message,
          }));
        }
      },

      // 看著一則後端回覆直到結束。open(onEvent, onDone, onError) 開始連線、回 AbortController
      _followRun(convId, msgId, open) {
        const run = { convId, msgId };
        const mine = () => get()._run === run;
        let done = null;
        let usage = null; // 這次回覆的 context 用量（自動壓縮只看它）
        const numCtx = (u) => ({ prompt_tokens: u.prompt_tokens, num_ctx: u.num_ctx || get().settings.numCtx });
        set({ streaming: true, _run: run });
        const abort = open(
          (e) => {
            if (!mine()) return;
            if (e.type === "done") done = e;
            else if (e.type === "saved") get()._advanceBase(convId, e.prev, e.updated_at);
            else if (e.type === "snapshot") {
              get()._applySnapshot(convId, e);
              if (e.usage) usage = numCtx(e.usage);
              if (e.saved) get()._advanceBase(convId, e.saved[0], e.saved[1]);
            } else {
              if (e.type === "usage") usage = numCtx(e);
              get()._applyChatEvent(convId, msgId, e);
            }
          },
          () => {
            if (!mine()) return;
            if (done) get()._finishRun(convId, msgId, done, usage);
            else get()._lostRun(convId, msgId); // 連線先斷了，回覆可能還在跑
          },
          (err) => {
            if (mine()) get()._lostRun(convId, msgId, err);
          }
        );
        set({ _abort: abort });
      },

      // 中途接上：目前內容直接換上去（本機可能是舊的或還沒這則）
      _applySnapshot(convId, e) {
        set((st) => ({
          conversations: st.conversations.map((c) => {
            if (c.id !== convId || !Array.isArray(c.messages)) return c;
            const has = c.messages.some((m) => m.id === e.id);
            return {
              ...c,
              messages: has
                ? c.messages.map((m) => (m.id === e.id ? { ...m, ...e.message } : m))
                : [...c.messages, { id: e.id, role: "assistant", ...e.message }],
            };
          }),
        }));
        if (e.usage) set({ usage: { ...e.usage, num_ctx: e.usage.num_ctx || get().settings.numCtx } });
      },

      // 回覆結束：後端已經存好了，這裡不用（也不能）再存一次，以免舊內容蓋掉後端的
      _finishRun(convId, msgId, done, usage) {
        get()._patchMessageIn(convId, msgId, (m) => ({
          status: "done",
          toolRunning: false,
          progress: null,
          content: stripEchoedNote(m.content),
        }));
        set({ streaming: false, _abort: null, _run: null });
        get()._advanceBase(convId, done.prev_updated_at, done.updated_at);
        get()._maybeAutoCompact(convId, usage);
      },

      // 連線斷了但沒收到結束：回覆多半還在後端跑，接回去；後端連不上才顯示錯誤
      async _lostRun(convId, msgId, err) {
        set({ streaming: false, _abort: null, _run: null });
        if (err?.status === 409) {
          // 別的分頁正在這個對話回覆：這則不會跑，下次同步就看得到那邊的回覆
          const patch = { status: "done", error: err.message, toolRunning: false };
          get()._patchMessageIn(convId, msgId, patch);
          // 存好之後接上那邊的回覆（它可能不是最後一則了）
          get()
            ._syncConversation(convId, (c) => withMessagePatch(c, msgId, patch))
            .then(() => get()._resumeRun(convId));
          return;
        }
        for (const wait of [300, 1500, 3000, 5000]) {
          await new Promise((r) => setTimeout(r, wait));
          try {
            await get()._resumeRun(convId, { strict: true, reason: err?.status ? err.message : undefined });
            return;
          } catch {
            /* 後端還連不上：等一下再試 */
          }
        }
        // 還是連不上：訊息留在回覆中，定期同步（refreshConversations）會再確認，連回來就接上或標成中斷
        get()._patchMessageIn(convId, msgId, { error: err?.message || "連線中斷", toolRunning: false, progress: null });
      },

      // 對話停在「回覆中」：還在跑就接上；已經沒在跑就以後端存的為準。
      // 順序不能換：先查 run 再讀對話，後端是存好才移除 run，讀到的才會是最後結果。
      async _resumeRun(convId, { strict = false, reason } = {}) {
        // 停在回覆中的訊息：不一定是最後一則（回覆在跑的時候別處又送了問題，問題和回覆會接在它後面）
        const pendingIds = () =>
          (get().conversations.find((c) => c.id === convId)?.messages || [])
            .filter((m) => m.role === "assistant" && m.status === "streaming")
            .map((m) => m.id);
        if (get().streaming || get()._resuming === convId || !pendingIds().length) return;
        set({ _resuming: convId });
        try {
          const run = await getChatRun(convId);
          const full = await getConversation(convId);
          if (get().streaming) return;
          get()._updateConversation(convId, { ...full, messages: full.messages || [] });
          // 還在跑的那則接上；其他停在回覆中的都沒在跑：後端中途重啟了（或一開始就沒跑起來）。已存的部分留著
          const stale = pendingIds().filter((id) => !(run.running && id === run.message_id));
          if (stale.length) {
            const patch = {
              status: "done",
              toolRunning: false,
              progress: null,
              ...(reason ? { error: reason } : { interrupted: true }),
            };
            for (const id of stale) get()._patchMessageIn(convId, id, patch);
            // 存檔衝突時只標還停在回覆中的那幾則（別處已經標好就不動）
            get()._syncConversation(convId, (c) => {
              let out = null;
              for (const id of stale) {
                out = withMessagePatch(out || c, id, (m) => (m.status === "streaming" ? patch : null)) || out;
              }
              return out;
            });
          }
          if (run.running) {
            get()._followRun(convId, run.message_id, (...cb) => followChatRun(convId, ...cb));
          }
        } catch (e) {
          if (strict) throw e; // 其他時候後端連不上就算了，下次同步再確認
        } finally {
          set({ _resuming: null });
        }
      },

      // ---- 送出訊息（核心）----
      async sendMessage(text) {
        const trimmed = text.trim();
        if (!trimmed || get().streaming) return;

        if (Date.now() - get()._lastRefresh > 5000) {
          await get().refreshConversations();
        }
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
        // /workflow 專案:圖 輸入 → 執行 LangGraph 工作流
        if (trimmed === "/workflow" || /^\/workflow\s/.test(trimmed)) {
          await get()._handleSlashWorkflow(trimmed.slice(9).trim());
          return;
        }

        // 這則對話在後端還有回覆在跑（別的分頁 / 裝置送的）：後端不會再開一個（409），所以不送出——
        // 文字放回輸入框、輸入框上方提示，並接上那個回覆
        if (await getChatRun(convId).then((r) => r.running, () => false)) {
          set({ composerDraft: trimmed, syncNotice: { kind: "busy", title: convo.title } });
          try {
            const full = await getConversation(convId);
            get()._updateConversation(convId, { ...full, messages: full.messages || [] });
          } catch {
            /* 連不上：下次同步再接 */
          }
          get()._resumeRun(convId);
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

        // 問題和空的回覆接在最後，首則訊息設為標題（存檔衝突時在後端最新版上也這樣接）
        const add = (c) => withMessages(c, [userMsg, assistantMsg], trimmed.slice(0, 30));
        _unsaved.add(userMsg.id).add(assistantMsg.id);
        set((st) => ({
          conversations: st.conversations.map((c) => (c.id === convId ? add(c) : c)),
          streaming: true,
          syncNotice: null,
        }));
        get().clearAttachments();

        // 先把問題和空的回覆存好：回覆在後端跑，關掉網頁問題也不會不見，後端也才有地方寫。
        // 本機的版本舊了（別的分頁 / 裝置剛存過）就接在後端最新版後面，送給模型的歷史也用存好的這份
        const saveErr = await get()._syncConversation(convId, add);
        _unsaved.delete(userMsg.id);
        _unsaved.delete(assistantMsg.id);
        if (saveErr) {
          get()._patchMessageIn(convId, assistantMsg.id, { status: "done", error: saveErr.message });
          if (saveErr.reason === "deleted") set({ composerDraft: trimmed }); // 對話已在別處刪除：問題放回輸入框
          set({ streaming: false });
          return;
        }

        // 組送出的訊息（帶 role+content；有附件則帶 images 供 vision/img2img）
        const sendable = (get().conversations.find((c) => c.id === convId)?.messages || [])
          .filter((m) => m.role === "user" || m.role === "assistant")
          .filter((m) => m.id !== assistantMsg.id);
        // PNG info 只附在「最後一則」有圖的助理訊息（問參數幾乎都是問最近那張）。
        // 每則都附會讓歷史充滿 prompt 純文字範本 → 模型模仿著印文字而忘記呼叫工具。
        let lastGenIdx = -1;
        if (settings.sendGenInfo !== false) {
          for (let i = sendable.length - 1; i >= 0; i--) {
            const m = sendable[i];
            if (m.role === "assistant" && m.images?.length) {
              lastGenIdx = i;
              break;
            }
          }
        }
        const history = sendable.map((m, i) => {
          const base = {
            role: m.role,
            content: m.role === "assistant" ? stripEchoedNote(m.content) : m.content,
          };
          if (i === lastGenIdx) {
            base.content = (m.content || "") + genInfoForModel(m.images);
          }
          if (m.attachments?.length) {
            base.images = m.attachments.map((a) => stripPrefix(a.dataUrl));
          }
          // 助理訊息裡生成 / 編輯出的圖（只帶網址）：讓編輯技能能直接改「剛剛那張」
          if (m.role === "assistant" && m.images?.length) {
            const urls = m.images.map((im) => im?.url).filter((u) => typeof u === "string" && u.startsWith("/images/"));
            if (urls.length) base.generated_images = urls;
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

        const canTools = get().modelSupportsTools(model);
        const toolsEnabled = settings.toolsEnabled && canTools;
        const webEnabled = settings.webEnabled && canTools;
        // 取當前引擎自己的 effort；codex / claude 依所選模型能力修正
        // （例如設定殘留 gpt-6-sol 才有的 ultra、卻換到 gpt-6-luna → 退回 medium，避免 CLI 報錯；
        // claude-haiku-4-5 宣告空清單＝不支援，後端不會送 --effort）
        let effort = normEffort(settings.effort)[effortKeyFor(settings.engine)];
        if (["codex", "claude_cli", "strata"].includes(settings.engine)) {
          const supported = get().models.find((m) => m.name === model)?.efforts;
          if (supported?.length && !supported.includes(effort)) {
            effort = supported.includes("medium") ? "medium" : supported[0];
          }
        }

        get()._followRun(convId, assistantMsg.id, (onEvent, onDone, onError) =>
          streamChat(
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
                skill: skillParam(settings),
              conversationId: convId,
              messageId: assistantMsg.id,
            },
            onEvent,
            onDone,
            onError
          )
        );
      },

      // /workflow：執行 LangGraph 工作流。每一步寫進可收合的過程區塊，生成的圖照常顯示，
      // 最終輸出寫成回覆（messages 取最後一則 AI 訊息，其他欄位逐一列出）。
      // 只打 /workflow 列出可用的工作流。輸入像 JSON 物件就當 JSON，否則當一段文字。
      async _handleSlashWorkflow(rest) {
        const m = /^(\S+)\s*([\s\S]*)$/.exec(rest || "");
        const target = m?.[1] || "";
        const raw = (m?.[2] || "").trim();
        const userMsg = { id: uid(), role: "user", content: `/workflow ${rest}`.trim() };
        const assistantMsg = {
          id: uid(),
          role: "assistant",
          content: "",
          thinking: "",
          images: [],
          status: "streaming",
          toolRunning: !!target,
          toolName: target ? `workflow ${target}` : "",
        };
        // 綁定開始時的對話：跑到一半切去別的對話，也是改、存原本那則
        const convId = get().currentId;
        const title = `/workflow ${target}`.slice(0, 30);
        _unsaved.add(userMsg.id).add(assistantMsg.id);
        set((st) => ({
          conversations: st.conversations.map((c) =>
            c.id === convId ? withMessages(c, [userMsg, assistantMsg], title) : c
          ),
          streaming: true,
          syncNotice: null,
        }));
        const patch = (p) => get()._patchMessageIn(convId, assistantMsg.id, p);
        const finish = (p = {}) => {
          patch({ status: "done", toolRunning: false, progress: null, ...p });
          set({ streaming: false, _abort: null });
          get()._saveNewMessages(convId, [userMsg.id, assistantMsg.id], title);
        };

        if (!target) {
          try {
            const data = await fetchWorkflows();
            const names = data.projects.flatMap((p) => (p.graphs || []).map((g) => `\`${p.slug}:${g}\``));
            finish({
              content:
                "`/workflow 專案:圖 輸入`（輸入可以是 JSON 物件或一段文字）\n\n" +
                (names.length ? names.join("、") : "（還沒有工作流，請到 LangGraph 工作流頁面建立）") +
                (data.enabled ? "" : "\n\n⚠️ 工作流頁面還沒「允許執行」。"),
            });
          } catch (e) {
            finish({ error: e.message });
          }
          return;
        }

        let input = raw;
        if (raw.startsWith("{")) {
          try {
            input = JSON.parse(raw);
          } catch (e) {
            finish({ error: `JSON: ${e.message}` });
            return;
          }
        }
        const { settings, models } = get();
        let effort = normEffort(settings.effort)[effortKeyFor(settings.engine)];
        const supported = models.find((x) => x.name === settings.chatModel)?.efforts;
        if (supported?.length && !supported.includes(effort)) {
          effort = supported.includes("medium") ? "medium" : supported[0];
        }
        const step = (line) => patch((msg) => ({ thinking: (msg.thinking || "") + line + "\n" }));
        const short = (v) => {
          const t = JSON.stringify(v);
          return !t || t === "null" ? "" : t.length > 160 ? `${t.slice(0, 160)}…` : t;
        };
        const abort = runWorkflow(
          {
            target,
            input,
            engine: settings.engine,
            model: settings.chatModel,
            think: settings.think,
            effort,
            num_ctx: settings.numCtx,
            image_settings: settings.imageSettings,
            source: "chat",
          },
          (e) => {
            if (e.type === "run") step(`▶ ${e.project}:${e.graph}（${e.engine} / ${e.model}）`);
            else if (e.type === "node") step(`✓ ${e.ns ? `${e.ns}/` : ""}${e.node} ${short(e.update)}`);
            else if (e.type === "llm") step(`  · ${e.node}: LLM${e.images ? `（看 ${e.images} 張圖）` : ""}`);
            else if (e.type === "note") step(`  · ${e.node ? `${e.node}: ` : ""}${e.text}`);
            else if (e.type === "log" || e.type === "stderr") step(`  ${e.text}`);
            else if (e.type === "call_error") step(`  ✗ ${e.fn}: ${e.message}`);
            else if (e.type === "progress") {
              patch({ toolRunning: true, toolName: "generate_image", progress: {
                value: e.value || 0, step: e.step, steps: e.steps,
                preview: e.preview ? `data:image/png;base64,${e.preview}` : null,
              } });
            } else if (e.type === "image") {
              patch((msg) => ({
                toolName: `workflow ${target}`,
                progress: null,
                images: [...(msg.images || []), { url: e.url, params: e.params, info: e.info || "", at: 0 }],
              }));
            } else if (e.type === "sources") {
              patch((msg) => ({ sources: [...(msg.sources || []), ...(e.results || [])] }));
            } else if (e.type === "done") {
              patch((msg) => {
                const shown = new Set((msg.images || []).map((im) => im.url));
                const extra = imagesIn(e.output).filter((u) => !shown.has(u)).map((url) => ({ url, at: 0 }));
                return {
                  content: outputText(e.output) || "✓",
                  images: [...(msg.images || []), ...extra],
                  toolRunning: false,
                  progress: null,
                };
              });
            } else if (e.type === "error") patch({ error: e.message });
          },
          () => finish(),
          (err) => finish({ error: err.message })
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
        // 綁定開始時的對話：生成中切去別的對話，也是改、存原本那則
        const convId = get().currentId;
        const title = prompt.slice(0, 30);
        _unsaved.add(userMsg.id).add(assistantMsg.id);
        set((st) => ({
          conversations: st.conversations.map((c) =>
            c.id === convId ? withMessages(c, [userMsg, assistantMsg], title) : c
          ),
          streaming: true,
          syncNotice: null,
        }));
        try {
          const result = await generateImage(
            prompt,
            settingsOverride || get().settings.imageSettings
          );
          get()._patchMessageIn(convId, assistantMsg.id, {
            toolRunning: false,
            status: "done",
            images: [
              { url: result.url, params: result.params, info: result.info || "" },
            ],
          });
        } catch (e) {
          get()._patchMessageIn(convId, assistantMsg.id, {
            toolRunning: false,
            status: "done",
            error: e.message,
          });
        } finally {
          set({ streaming: false });
          await get()._saveNewMessages(convId, [userMsg.id, assistantMsg.id], title);
        }
      },

      // /image、/workflow 結束：把這次加的訊息（本機的最後內容）存回後端；存完才不算「還沒存」
      async _saveNewMessages(convId, ids, title) {
        const c = get().conversations.find((x) => x.id === convId);
        const msgs = ids.map((id) => c?.messages?.find((m) => m.id === id)).filter(Boolean);
        if (msgs.length) await get()._syncConversation(convId, (cv) => withMessages(cv, msgs, title));
        for (const id of ids) _unsaved.delete(id);
      },

      // ---- 提示詞歷史（sd-webui-prompt-history 整合）----
      // 把要塞進輸入框的草稿交給 Composer 取用（取用後 Composer 會清回 null）
      setComposerDraft(text) {
        set({ composerDraft: text });
      },

      // 把片段「附加」到輸入框（Composer 取用後會清回 null）；保留使用者已輸入的內容
      insertComposer(text) {
        set({ composerInsert: text });
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

      // LoRA 直接生成：用 <lora:name:1> + 觸發詞立刻生一張
      async generateLora(c) {
        const name = typeof c === "string" ? c : c?.name;
        const full = typeof c === "object" ? (c?.prompt || "").trim() : "";
        if (get().streaming || !name) return;
        let convo = get().currentConversation();
        if (!convo) {
          get().createConversation();
          convo = get().currentConversation();
        }
        await get()._ensureLoaded(convo.id);
        const body = full || `<lora:${name}:1>`;
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

      async stopStreaming() {
        const run = get()._run;
        if (run) {
          try {
            await cancelChatRun(run.convId); // 後端停好會送 done，_finishRun 收尾
            return;
          } catch {
            /* 後端連不上：至少不再接收 */
          }
        }
        get()._abort?.abort();
        set({ streaming: false, _abort: null, _run: null });
      },

      // 自動壓縮：設定開啟且剛結束的那次回覆用量達門檻（預設 80%）就壓縮「那則」對話
      //（回覆中切到別的對話也一樣，不會壓到目前開著的）；compact 本身會擋太短的對話
      _maybeAutoCompact(convId, usage) {
        const { settings } = get();
        if (!settings.autoCompact || !usage?.num_ctx || !usage.prompt_tokens) return;
        const at = Number(settings.autoCompactAt) || 0.8;
        if (usage.prompt_tokens / usage.num_ctx >= at) get().compact(convId);
      },

      // 壓縮對話：把較舊訊息摘要成一則，保留最後一組往返，省 context。
      // 綁定開始時的那則對話（convId，預設目前對話）：摘要回來前切到別的對話，也只改原本那則。
      // 壓縮期間才加進來的訊息（這裡送出的、別處存的）接在摘要與保留的那組後面，不會被丟掉
      async compact(convId) {
        const id = typeof convId === "string" ? convId : get().currentId;
        const convo = get().conversations.find((c) => c.id === id);
        if (!convo || !Array.isArray(convo.messages) || get().streaming || get().compacting) return;
        const turns = convo.messages.filter(
          (m) => m.role === "user" || m.role === "assistant"
        );
        if (turns.length < 3) return; // 太短不必壓縮
        const model = convo.model || get().settings.chatModel;
        const payload = turns.map((m) => ({ role: m.role, content: m.content }));

        set({ compacting: id });
        try {
          const { summary, notices } = await compactConversation(
            model,
            payload,
            get().settings.numCtx,
            get().settings.engine,
            ["ollama", "strata"].includes(get().settings.engine) ? !!get().settings.think : undefined
          );
          if (!summary) return;
          const before = new Set(convo.messages.map((m) => m.id)); // 開始壓縮時已有的：換成摘要
          const keep = new Set(convo.messages.slice(-2).map((m) => m.id)); // 保留最後一組往返
          const summaryMsg = {
            id: uid(),
            role: "assistant",
            content: summary,
            compacted: true,
            // 後端提醒（例如思考沒給出答案、改用不思考產生摘要），顯示在摘要標記旁
            notices: Array.isArray(notices) && notices.length ? notices : undefined,
            status: "done",
          };
          const redo = (c) => ({
            ...c,
            messages: [
              summaryMsg,
              ...(c.messages || []).filter(
                (m) => m.id !== summaryMsg.id && (keep.has(m.id) || !before.has(m.id))
              ),
            ],
          });
          set((st) => ({
            conversations: st.conversations.map((c) =>
              c.id === id && Array.isArray(c.messages) ? redo(c) : c
            ),
          }));
          if (get().currentId === id) set({ usage: null });
          get()._syncConversation(id, redo);
        } catch (e) {
          /* 摘要失敗：保持原樣 */
        } finally {
          set({ compacting: null });
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

// 跨裝置同步的觸發點：分頁重新可見、視窗取得焦點、以及每 30 秒（僅在可見時）
if (typeof window !== "undefined" && typeof document !== "undefined") {
  const refresh = () => {
    if (document.visibilityState === "visible") {
      useChat.getState().refreshConversations();
    }
  };
  document.addEventListener("visibilitychange", refresh);
  window.addEventListener("focus", refresh);
  window.setInterval(refresh, 30_000);
}
