// 漫畫工作室狀態：劇本、故事、角色卡、分鏡格、出圖設定、對白氣泡。
// 流程：劇情大綱 → AI 撰寫故事（可改）→ 依故事分鏡（每格一個 beat）→ 出圖 → 看圖檢查，
// 不符合就依檢查意見重寫這格關鍵字再畫（最多 MAX_AUTO_FIX 次）。
// 出圖重用 lib/api.js 的 generateImage（txt2img）；故事、分鏡、看圖檢查用 lib/comicApi.js。
import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import {
  addComicVersion,
  deleteComicRemote,
  deleteComicVersionRemote,
  generateImage,
  getComic,
  getComicVersion,
  listComics,
  listComicVersions,
  putComic,
  saveComicPage,
} from "../lib/api";
import {
  checkComicPanel,
  generateStoryboard,
  parseComicCharacters,
  regeneratePanelPrompt,
  writeComicStory,
} from "../lib/comicApi";
import { useChat } from "./chat";
import { isExpressionTag, splitTags, tagKey } from "../comic/expressionTags";
import { defaultTail } from "../comic/bubbleShape";
import { autoName, findCard, hasName, sameName } from "../comic/names";
import { comicT } from "../comic/comicI18n";
import { deepRenameLoraTags } from "../lib/loraTags";

// 作品內容（會存到伺服器的欄位）；這些欄位任一變動就 debounce 自動儲存
const PROJECT_KEYS = [
  "title",
  "premise",
  "story",
  "systemPrompt",
  "systemBase",
  "skills",
  "promptMode",
  "panelCount",
  "think",
  "style",
  "negative",
  "characters",
  "settings",
  "layout",
  "panels",
  "panelsStory",
  "pageUrl",
];
const AUTOSAVE_MS = 1500;
// 自動儲存的計時器、進行中的儲存（同一時間只送一個 PUT，依序存）
let _saveTimer = null;
let _saving = null;
// 每次作品內容變動 +1：儲存成功時內容沒再變過，才算存好（dirty=false）
let _editSeq = 0;
// 換作品（開別的作品 / 新作品 / 匯入）進行中：非同步步驟的結果等換完再決定寫到哪一份
let _switching = null;
// 寫回伺服器上「已不是目前開著的」原作品：依序做；換作品前先等它們做完，開到的才是新的
let _remote = Promise.resolve();
// 這個分頁刪掉的作品：之後的儲存 / 寫回都略過，不會被存回來
const _deleted = new Set();
// 進頁面的同步只跑一個（StrictMode / 很快地進出頁面時不會重複另存）
let _syncing = null;
// 存檔失敗後自動重試：3 秒、10 秒、30 秒，之後每 60 秒一次，直到存上去。
// 只重試失敗的那份作品：換了作品、作品被刪、已經沒有待存的修改就不再試。
// how：重試做什麼（預設再存一次；進頁面時連不上伺服器則是再對一次伺服器）
const RETRY_MS = [3000, 10000, 30000, 60000];
let _retryTimer = null;
let _retryStep = 0;
function scheduleRetry(id, how = "save") {
  clearTimeout(_retryTimer);
  const ms = RETRY_MS[Math.min(_retryStep, RETRY_MS.length - 1)];
  _retryStep += 1;
  _retryTimer = setTimeout(() => {
    _retryTimer = null;
    const st = useComic.getState();
    if (st.projectId !== id || !st.dirty || st.remoteGone || _deleted.has(id) || _switching) return;
    if (how === "sync") st.syncProject();
    else st.saveProject();
  }, ms);
}
function cancelRetry() {
  clearTimeout(_retryTimer);
  _retryTimer = null;
  _retryStep = 0;
}
// 自動儲存的 debounce 計時器（編輯時、刪除失敗要恢復時用）
function armAutosave() {
  clearTimeout(_saveTimer);
  _saveTimer = setTimeout(() => {
    _saveTimer = null;
    useComic.getState().saveProject();
  }, AUTOSAVE_MS);
}
// 分鏡版本：整份歷史存在伺服器（不設上限）；瀏覽器只快取最近幾版（含分鏡格內容），
// 更早的版本預覽 / 回復時再向伺服器取
const VERSION_CACHE = 5;
const clone = (v) => JSON.parse(JSON.stringify(v));
const versionSummary = ({ panels, pending, ...rest }) => rest;

const pickProject = (st) => Object.fromEntries(PROJECT_KEYS.map((k) => [k, st[k]]));
const sameProject = (a, b) =>
  PROJECT_KEYS.every((k) => JSON.stringify(a[k] ?? null) === JSON.stringify(b[k] ?? null));
// 改作品裡某一格（作品可以是目前的 store 或伺服器上的那份）；找不到這格回 null
const patchPanel = (proj, id, change) => {
  const panels = Array.isArray(proj.panels) ? proj.panels : [];
  const cur = panels.find((p) => p.id === id);
  if (!cur) return null;
  const patch = typeof change === "function" ? change(cur) : change;
  return { panels: panels.map((p) => (p.id === id ? { ...p, ...patch } : p)) };
};
// 分鏡版本（本機快取與伺服器共用的格式）；story＝這組分鏡對應的故事
const makeVersion = (panels, { label, premise, story }) => ({
  id: uid(),
  at: Date.now(),
  label,
  premise: premise || "",
  story: story || "",
  count: panels.length,
  images: panels.filter((p) => p.image?.url).length,
  cover: panels.find((p) => p.image?.url)?.image.url || "",
  panels: clone(panels),
});
// AI 重新分鏡前存的版本用「這組分鏡當初依據的故事」：使用者常先改好故事再重新分鏡，
// 存當下的故事會跟這組分鏡對不上。其他時候（手動、回復前）存畫面上的故事。
const versionStory = (proj, label) =>
  label === "auto" && typeof proj.panelsStory === "string" && proj.panelsStory.trim()
    ? proj.panelsStory
    : proj.story || "";
const unsavedError = () => Object.assign(new Error("unsaved"), { code: "unsaved" });
const projectIsEmpty = (st) =>
  !st.panels.length &&
  !st.premise.trim() &&
  !(st.story || "").trim() &&
  !st.title.trim() &&
  !st.characters.length;

// 每格「表情」在提示詞裡的強調權重：放在畫風之後、角色固定 tag 之前，
// 並用 (…:1.2) 加權，否則會被角色卡 20 幾個固定 tag 與 LoRA 壓過去而每格同一張臉。
const EXPRESSION_WEIGHT = 1.2;

// 看圖檢查不符合時，依檢查意見重寫關鍵字再畫的次數上限（每格每次出圖）
const MAX_AUTO_FIX = 2;
const CHECK_BUSY = ["checking", "fixing"];
export const isCheckBusy = (check) => !!check && CHECK_BUSY.includes(check.status);

const uid = () =>
  (crypto.randomUUID && crypto.randomUUID()) ||
  Math.random().toString(36).slice(2);

const clamp01 = (v) => Math.max(0.04, Math.min(0.96, v));

const DEFAULT_SETTINGS = {
  width: 896,
  height: 1152,
  steps: 28,
  cfg_scale: 5,
  sampler_name: "Euler a",
  sd_model_checkpoint: "",
  lockSeed: true,
  seed: -1, // -1＝首次生成時抽一個固定下來（鎖定時跨格共用）；不鎖定時每格每次隨機
  checkModel: "", // 看圖檢查用的模型；空＝自動（頂列的模型能看圖就用它，否則挑第一個能看圖的）
};

const DEFAULT_LAYOUT = { columns: 2, gutter: 14, bg: "#f5f5f4" };

// 角色卡：角色關鍵字（使用者貼的範例 prompt）由 LLM 拆成人物特徵、預設服裝、範例姿勢、範例場景。
// 人物特徵、服裝是每格的預設；姿勢、場景只是範例，分鏡時 AI 依故事寫在各格。
// parsed_from＝上次解析的關鍵字，跟目前的不同就是「還沒解析」，寫故事 / 分鏡前會自動解析。
// 舊卡只有 appearance：當成角色關鍵字；還沒解析時整段當固定外觀（跟以前一樣）。
const newCharacter = () => ({
  id: uid(),
  name: "",
  keywords: "",
  lora: "",
  features: "",
  outfit: "",
  pose: "",
  scene: "",
  parsed_from: "",
});
export const cardKeywords = (c) => (c.keywords ?? c.appearance ?? "").trim();
export const isParsed = (c) => !!c.parsed_from && c.parsed_from === cardKeywords(c);
export const cardFeatures = (c) => (isParsed(c) ? c.features || "" : cardKeywords(c));
export const cardOutfit = (c) => (isParsed(c) ? c.outfit || "" : "");
const parsedField = (c, field) => (isParsed(c) ? c[field] || "" : "");
// 給後端的角色卡：appearance＝人物特徵＋預設服裝（圖片說故事等舊流程也看得懂）
const castPayload = (cards) =>
  cards
    .filter((c) => c.name.trim())
    .map((c) => ({
      name: c.name.trim(),
      appearance: [cardFeatures(c), cardOutfit(c)].filter((x) => x.trim()).join(", "),
      features: parsedField(c, "features"),
      outfit: cardOutfit(c),
      pose: parsedField(c, "pose"),
      scene: parsedField(c, "scene"),
    }));
// 一格裡各角色的 {features, pose, outfit}（這格寫了或換掉的部分；空的用角色卡）。
// 舊格子只有 outfits {名字: 服裝}：讀的時候併進來，寫回時一律寫 looks 並清掉 outfits。
export const LOOK_FIELDS = ["features", "pose", "outfit"];
export const panelLooks = (p) => {
  const out = {};
  for (const [k, v] of Object.entries(p?.outfits || {})) if ((v || "").trim()) out[k] = { outfit: v };
  for (const [k, v] of Object.entries(p?.looks || {})) {
    if (!v || typeof v !== "object") continue;
    const got = Object.fromEntries(LOOK_FIELDS.filter((f) => (v[f] || "").trim()).map((f) => [f, v[f]]));
    out[k] = { ...out[k], ...got };
  }
  return Object.fromEntries(Object.entries(out).filter(([, v]) => Object.keys(v).length));
};
export const lookOf = (p, name) =>
  Object.entries(panelLooks(p)).find(([k]) => sameName(k, name))?.[1] || {};
// 改某格某角色的一欄（空白＝刪掉，回到角色卡的）
const withLook = (p, name, field, value) => {
  const looks = panelLooks(p);
  const key = Object.keys(looks).find((k) => sameName(k, name)) ?? name;
  const entry = { ...(looks[key] || {}) };
  if ((value || "").trim()) entry[field] = value;
  else delete entry[field];
  const rest = Object.fromEntries(Object.entries(looks).filter(([k]) => k !== key));
  return { looks: Object.keys(entry).length ? { ...rest, [key]: entry } : rest, outfits: undefined };
};
// 換名字 / 刪角色時，分鏡格的 looks 跟著改
const renameKey = (obj, from, to) =>
  Object.fromEntries(
    Object.entries(obj || {})
      .filter(([k]) => to || !sameName(k, from))
      .map(([k, v]) => [sameName(k, from) ? to : k, v])
  );

const newPanel = (patch = {}) => ({
  id: uid(),
  beat: "", // 這格演的是哪一段故事（依故事分鏡時由 AI 寫，可改）；看圖檢查拿它比對
  prompt: "",
  description: "", // 英文句子（Anima 等讀得懂自然語言的 checkpoint）；出圖時整段放在標籤前
  expression: "", // 該格表情（danbooru tag，逗號分隔）；獨立於場景 prompt
  characters: [],
  looks: {}, // 各角色這格的 {features, pose, outfit}；沒寫的欄位用角色卡的（姿勢沒有預設）
  bubbles: [],
  image: null, // {url, params, info}
  status: "idle", // idle | generating | done | error
  error: "",
  seed: null, // 實際用到的 seed（出圖後回填）
  // 看圖檢查：{status: checking | fixing | pass | gave_up | skipped | error, attempts, problems, fix, reason}
  check: null,
  ...patch,
});

// 給後端的一格劇本（分鏡、單格重寫、看圖檢查共用）
const panelScript = (p) => ({
  beat: p.beat || "",
  prompt: p.prompt,
  description: p.description || "",
  expression: p.expression,
  characters: p.characters,
  looks: panelLooks(p),
  dialogue: (p.bubbles || [])
    .filter((b) => b.type !== "caption" && (b.text || "").trim())
    .map((b) => ({ speaker: b.speaker || "", text: b.text })),
  caption: (p.bubbles || []).find((b) => b.type === "caption")?.text || "",
});

// ---- 讀進作品時補齊欄位 ----
// 直接打 API、手做的資料或很舊的作品可能少欄位、型別不對（例如格子沒有 bubbles）。從伺服器開作品、
// 瀏覽器還原、取回版本、寫回原作品時都先整理一次，畫面和出圖才不會整頁掛掉；壞掉的格子 / 角色卡略過。
const DEFAULT_STYLE = "masterpiece, best quality, amazing quality";
const DEFAULT_NEGATIVE = "lowres, bad anatomy, worst quality, bad hands, text, watermark";
const isObj = (v) => !!v && typeof v === "object" && !Array.isArray(v);
const str = (v) => (typeof v === "string" ? v : v == null ? "" : String(v));
const num = (v, d) => (typeof v === "number" && Number.isFinite(v) ? v : d);
const normBubble = (b) => {
  const type = typeof b.type === "string" && b.type ? b.type : "speech";
  return {
    ...b,
    id: b.id || uid(),
    type,
    tail: typeof b.tail === "string" && b.tail ? b.tail : defaultTail(type),
    speaker: str(b.speaker),
    text: str(b.text),
    x: num(b.x, 0.5),
    y: num(b.y, type === "caption" ? 0.88 : 0.25),
    w: num(b.w, type === "caption" ? 0.86 : 0.42),
  };
};
const normPanel = (p) => {
  if (!isObj(p)) return null;
  const image = isObj(p.image) && p.image.url ? p.image : null;
  return {
    ...newPanel(),
    ...p,
    id: p.id || uid(),
    beat: str(p.beat),
    prompt: str(p.prompt),
    description: str(p.description),
    expression: str(p.expression),
    characters: Array.isArray(p.characters) ? p.characters.filter((n) => typeof n === "string") : [],
    looks: isObj(p.looks) ? p.looks : {},
    bubbles: Array.isArray(p.bubbles) ? p.bubbles.filter(isObj).map(normBubble) : [],
    image,
    status: typeof p.status === "string" && p.status ? p.status : image ? "done" : "idle",
    error: str(p.error),
    check: isObj(p.check) ? p.check : null,
  };
};
const normCharacter = (c) => {
  if (!isObj(c)) return null;
  return {
    ...newCharacter(),
    ...c,
    id: c.id || uid(),
    // 舊卡只有 appearance：當成角色關鍵字（cardKeywords 的讀法不變）
    keywords: typeof c.keywords === "string" ? c.keywords : str(c.appearance),
    ...Object.fromEntries(["name", "lora", "features", "outfit", "pose", "scene", "parsed_from"].map((k) => [k, str(c[k])])),
  };
};
// 回傳補齊後的作品（PROJECT_KEYS 以外的欄位，如 id / 時間戳，原樣保留）
const normalizeProject = (p) => ({
  ...p,
  ...Object.fromEntries(["title", "premise", "story", "systemPrompt", "systemBase", "panelsStory", "pageUrl"].map((k) => [k, str(p[k])])),
  skills: Array.isArray(p.skills) ? p.skills.filter((x) => typeof x === "string") : [],
  promptMode: typeof p.promptMode === "string" && p.promptMode ? p.promptMode : "auto",
  panelCount: num(p.panelCount, 6),
  think: !!p.think,
  style: typeof p.style === "string" ? p.style : DEFAULT_STYLE,
  negative: typeof p.negative === "string" ? p.negative : DEFAULT_NEGATIVE,
  characters: (Array.isArray(p.characters) ? p.characters : []).map(normCharacter).filter(Boolean),
  settings: { ...DEFAULT_SETTINGS, ...(isObj(p.settings) ? p.settings : {}) },
  layout: { ...DEFAULT_LAYOUT, ...(isObj(p.layout) ? p.layout : {}) },
  panels: (Array.isArray(p.panels) ? p.panels : []).map(normPanel).filter(Boolean),
});

// 頂列選的引擎／模型（跟聊天頁共用），以及看圖檢查要用的模型
function aiOptions(settings) {
  const chat = useChat.getState();
  const engine = chat.settings.engine;
  const model = chat.settings.chatModel;
  const models = chat.models || [];
  const canSee = (name) =>
    engine === "claude_cli" ||
    engine === "codex" ||
    !!models.find((m) => m.name === name)?.supports_vision;
  let checkModel = settings.checkModel || "";
  if (!checkModel || !models.some((m) => m.name === checkModel)) {
    checkModel = canSee(model) ? model : models.find((m) => m.supports_vision)?.name || model;
  }
  return { engine, model, lang: chat.settings.lang, numCtx: chat.settings.numCtx, checkModel };
}

// 由分鏡 API 的 dialogue/caption 推出預設氣泡位置（相對 0..1）。
function bubblesFromScript(dialogue, caption) {
  const bubbles = [];
  (dialogue || []).forEach((d, i) => {
    bubbles.push({
      id: uid(),
      type: "speech", // 樣式：speech | rect | shout | whisper | thought | caption
      tail: "down", // 尾巴方向（見 comic/bubbleShape.js TAIL_DIRS）
      speaker: d.speaker || "",
      text: d.text || "",
      x: clamp01(i % 2 === 0 ? 0.3 : 0.7),
      y: clamp01(0.18 + Math.floor(i / 2) * 0.22),
      w: 0.42,
    });
  });
  if (caption && caption.trim()) {
    bubbles.push({
      id: uid(),
      type: "caption",
      tail: "none",
      speaker: "",
      text: caption.trim(),
      x: 0.5,
      y: 0.88,
      w: 0.86,
    });
  }
  return bubbles;
}

export const useComic = create(
  persist(
    (set, get) => ({
      // ---- 劇本 ----
      title: "",
      premise: "",
      story: "", // AI 寫的（或使用者自己寫的）故事；分鏡依它切格
      systemPrompt: "", // 額外指示，接在 system 範本之後（指引 AI 寫故事與分鏡）
      systemBase: "", // 覆寫內建分鏡 system 範本；空＝用預設
      skills: [], // 分鏡時帶入的技能（slug）；說明接在 system 範本後面
      promptMode: "auto", // auto（checkpoint 是 Anima 才寫英文句子）| tags | sentences
      panelCount: 6,
      style: "masterpiece, best quality, amazing quality",
      negative: "lowres, bad anatomy, worst quality, bad hands, text, watermark",
      characters: [],
      settings: { ...DEFAULT_SETTINGS },
      layout: { ...DEFAULT_LAYOUT },
      panels: [],
      panelsStory: "", // 目前的分鏡格是依哪一版故事切的（AI 分鏡 / 回復版本時記下；存版本時用）
      view: "grid", // grid | page
      // ---- 伺服器端作品（永久保存）----
      projectId: null, // 伺服器上的作品 id；第一次有內容時建立
      pageUrl: "", // 最近一次匯出的整頁 PNG（存在圖片目錄）
      // 分鏡版本的本機快取（新到舊，最多 VERSION_CACHE 版）：{id, at, label, premise, count,
      // images, cover, panels, pending}；pending＝還沒送到伺服器（下次儲存成功時補送）。
      // AI 生成分鏡 / 匯入腳本 / 回復版本之前，都會先把目前的分鏡格整份存成一版
      versions: [],
      savedAt: null, // 最後一次成功儲存的時間（伺服器時間戳）
      saveState: "idle", // idle | saving | saved | error
      // 本機有還沒確認存上伺服器的修改（存檔失敗、存到一半、計時器還沒到就關頁）；會持久化，
      // 下次進漫畫工作室時補存
      dirty: false,
      // 這份作品存上去過、現在伺服器上已經沒有了（在別的裝置 / 別處刪除）：不再自動存（不建回來），
      // 本機修改留著，等使用者選「另存成新作品」或「捨棄」（執行期；重新整理後進頁面會再對一次）
      remoteGone: false,
      _loading: false, // 從伺服器載入中（避免觸發自動儲存）

      // ---- 執行期（不持久化）----
      storyboarding: false,
      storyWriting: false,
      parsingCast: false,
      notices: [], // 上次生成分鏡時後端的提醒（例如自動改用不思考），顯示在按鈕下方
      promptBusy: {}, // {panelId: true} 該格正在重新生成關鍵字
      promptError: {}, // {panelId: message}
      promptUndo: {}, // {panelId: {prompt, expression}} 重生前的關鍵字，可復原（再按一次換回來）
      // Ollama 思考型模型分鏡時是否先思考（較慢；某些模型會在思考裡打轉而沒有答案）
      think: false,
      genProgress: null, // {done, total}

      // ---- 一般 setter ----
      set(patch) {
        set(patch);
      },
      setSettings(patch) {
        set((st) => ({ settings: { ...st.settings, ...patch } }));
      },
      setLayout(patch) {
        set((st) => ({ layout: { ...st.layout, ...patch } }));
      },
      setView(view) {
        set({ view });
      },

      // ---- 角色卡 ----
      addCharacter() {
        set((st) => ({ characters: [...st.characters, newCharacter()] }));
      },
      updateCharacter(id, patch) {
        const before = get().characters.find((c) => c.id === id);
        set((st) => ({
          characters: st.characters.map((c) =>
            c.id === id ? { ...c, ...patch } : c
          ),
        }));
        // 改名時，分鏡格裡引用舊名字的地方跟著改，出圖才對得到這張卡
        const from = (before?.name || "").trim();
        const to = typeof patch.name === "string" ? patch.name.trim() : from;
        if (from && to && to !== from) {
          set((st) => ({
            panels: st.panels.map((p) => ({
              ...p,
              characters: p.characters.map((n) => (sameName(n, from) ? to : n)),
              looks: renameKey(panelLooks(p), from, to),
              outfits: undefined,
            })),
          }));
        }
      },
      removeCharacter(id) {
        const removed = get().characters.find((c) => c.id === id);
        set((st) => ({ characters: st.characters.filter((c) => c.id !== id) }));
        // 同步把分鏡格裡引用到的名字移除
        if (removed?.name?.trim()) {
          set((st) => ({
            panels: st.panels.map((p) => ({
              ...p,
              characters: p.characters.filter((n) => !sameName(n, removed.name)),
              looks: renameKey(panelLooks(p), removed.name, ""),
              outfits: undefined,
            })),
          }));
        }
      },

      // ---- 分鏡格 ----
      setPanel(id, patch) {
        set((st) => ({
          panels: st.panels.map((p) =>
            p.id === id
              ? { ...p, ...(typeof patch === "function" ? patch(p) : patch) }
              : p
          ),
        }));
      },
      addPanel() {
        set((st) => ({ panels: [...st.panels, newPanel()] }));
      },
      removePanel(id) {
        set((st) => ({ panels: st.panels.filter((p) => p.id !== id) }));
      },
      // LoRA 改名後（聊天裡的工具或 LoRA 管理的「檢查失效引用」）：目前作品裡的 <lora:舊名:…> 換成新名。
      // 伺服器上存的作品由後端換；這裡換開著的這份，免得自動儲存把舊名寫回去。
      replaceLoraNames(mapping) {
        if (!mapping || !Object.keys(mapping).length) return 0;
        const st = get();
        const patch = {};
        for (const k of PROJECT_KEYS) {
          const v = deepRenameLoraTags(st[k], mapping);
          if (v !== st[k]) patch[k] = v;
        }
        if (Object.keys(patch).length) set(patch);
        return Object.keys(patch).length;
      },
      setLook(panelId, name, field, value) {
        get().setPanel(panelId, (p) => withLook(p, name, field, value));
      },
      toggleCharacterInPanel(panelId, name) {
        get().setPanel(panelId, (p) => ({
          characters: hasName(p.characters, name)
            ? p.characters.filter((n) => !sameName(n, name))
            : [...p.characters, name],
        }));
      },

      // ---- 氣泡 ----
      addBubble(panelId, type = "speech") {
        get().setPanel(panelId, (p) => ({
          bubbles: [
            ...p.bubbles,
            {
              id: uid(),
              type,
              tail: defaultTail(type),
              speaker: "",
              text: "",
              x: 0.5,
              y: type === "caption" ? 0.88 : 0.25,
              w: type === "caption" ? 0.86 : 0.42,
            },
          ],
        }));
      },
      updateBubble(panelId, bubbleId, patch) {
        get().setPanel(panelId, (p) => ({
          bubbles: p.bubbles.map((b) =>
            b.id === bubbleId ? { ...b, ...patch } : b
          ),
        }));
      },
      removeBubble(panelId, bubbleId) {
        get().setPanel(panelId, (p) => ({
          bubbles: p.bubbles.filter((b) => b.id !== bubbleId),
        }));
      },

      // ---- 出圖提示詞 / 設定組裝 ----
      // 順序：畫風 → 英文句子（有的話）→ (表情:1.2) → 各角色的特徵、服裝、姿勢 / LoRA（濾掉表情類 tag）→ 場景。
      // 特徵、服裝：這格有寫就用這格的，沒寫用角色卡的；姿勢只用這格的（角色卡的姿勢只是範例）。
      // 全程依 tag 去重（外觀與 LoRA 觸發詞常重複；場景若又寫了畫風詞也會被吃掉）；
      // 句子整段放、不拆不去重（裡面的逗號是句子的一部分）。「只有標籤」模式不帶句子。
      composePrompt(panel) {
        const { characters, style, promptMode } = get();
        const seen = new Set();
        const take = (tags, { dropExpression = false } = {}) => {
          const out = [];
          for (const t of tags) {
            const key = tagKey(t);
            if (!key || seen.has(key)) continue;
            if (dropExpression && isExpressionTag(t)) continue;
            seen.add(key);
            out.push(t);
          }
          return out;
        };

        const styleTags = take(splitTags(style));
        // 表情：expression 欄位 + 場景裡誤寫的表情 tag（舊分鏡格沒有 expression 欄位時仍能加權）
        const exprTags = take([
          ...splitTags(panel.expression),
          ...splitTags(panel.prompt).filter(isExpressionTag),
        ]);
        const present = [];
        for (const n of panel.characters || []) {
          const card = findCard(characters, n);
          if (card && !present.includes(card)) present.push(card);
        }
        const charTags = present.flatMap((c) => {
          const look = lookOf(panel, c.name);
          const tags = [look.features || cardFeatures(c), look.outfit || cardOutfit(c), look.pose, c.lora];
          return take(splitTags(tags.filter(Boolean).join(", ")), { dropExpression: true });
        });
        const sceneTags = take(splitTags(panel.prompt));
        const description =
          promptMode === "tags" ? "" : (panel.description || "").replace(/\s+/g, " ").trim();

        const parts = [
          styleTags.join(", "),
          description,
          exprTags.length
            ? `(${exprTags.join(", ")}:${EXPRESSION_WEIGHT})`
            : "",
          charTags.join(", "),
          sceneTags.join(", "),
        ].filter(Boolean);
        // 句子結尾（. ! ?）後面直接接空白，不再補逗號
        return parts.reduce(
          (out, part) => (!out ? part : /[.!?]$/.test(out) ? `${out} ${part}` : `${out}, ${part}`),
          ""
        );
      },

      // 鎖定種子時，把 -1 抽成一個固定值存回設定，之後各格共用同一 seed。
      _resolvedSeed() {
        const s = get().settings;
        if (!s.lockSeed) return -1;
        if (s.seed != null && s.seed !== -1) return s.seed;
        const seed = Math.floor(Math.random() * 2147483647);
        get().setSettings({ seed });
        return seed;
      },

      composeImageSettings() {
        const s = get().settings;
        return {
          width: Number(s.width) || 896,
          height: Number(s.height) || 1152,
          steps: Number(s.steps) || 28,
          cfg_scale: Number(s.cfg_scale) || 5,
          sampler_name: s.sampler_name || "Euler a",
          sd_model_checkpoint: s.sd_model_checkpoint || "",
          negative_prompt: get().negative || "",
          seed: get()._resolvedSeed(),
        };
      },

      // 把片段接到畫風（自動補逗號）；LoRA 瀏覽器「帶入」時用。
      appendStyle(text) {
        const piece = (text || "").trim();
        if (!piece) return;
        set((st) => {
          const base = (st.style || "").trim().replace(/[,，\s]*$/, "");
          return { style: base ? `${base}, ${piece}` : piece };
        });
      },

      // 套用「提示詞歷史」某筆的出圖參數到漫畫設定（參考用，不動劇本/分鏡）。
      applyHistorySettings(record) {
        const s = record.settings || {};
        const patch = {};
        if (s.width) patch.width = s.width;
        if (s.height) patch.height = s.height;
        if (s.steps != null) patch.steps = s.steps;
        if (s.cfg_scale != null) patch.cfg_scale = s.cfg_scale;
        if (s.sampler_name) patch.sampler_name = s.sampler_name;
        if (s.sd_model_checkpoint) patch.sd_model_checkpoint = s.sd_model_checkpoint;
        if (s.seed != null && s.seed !== -1) {
          patch.seed = s.seed;
          patch.lockSeed = true;
        }
        if (Object.keys(patch).length) get().setSettings(patch);
        const neg = s.negative_prompt ?? record.negative_prompt;
        if (neg != null) set({ negative: neg });
      },

      // 沒填名字但有外觀 / LoRA 的角色卡：自動命名，故事和分鏡才引用得到、出圖才帶得進去。
      // 回有名字的角色卡（給後端的 cast）。
      _namedCast(lang) {
        const characters = get().characters;
        let counter = 0;
        const named = characters.map((c) => {
          if (c.name.trim() || !(cardKeywords(c) || (c.lora || "").trim())) return c;
          let name;
          do {
            name = autoName(++counter, lang);
          } while (characters.some((o) => sameName(o.name, name)));
          return { ...c, name };
        });
        if (named.some((c, i) => c !== characters[i])) set({ characters: named });
        return named.filter((c) => c.name.trim());
      },

      // ---- 解析角色關鍵字：拆成人物特徵、預設服裝、範例姿勢、範例場景 ----
      // ids：只解析這些卡（不管有沒有解析過）；不給＝所有還沒解析的有名字的卡。
      // 關鍵字裡的 <lora:…> 不交給模型，角色卡還沒設 LoRA 時放進去。
      // 結果只寫回發起時的作品（見 _applyResult）；回傳「把解析結果套到一組角色卡」的函式（沒解析回 null）。
      async parseCharacters(opts = {}) {
        const ai = { ...aiOptions(get().settings), ...opts };
        const todo = get().characters.filter(
          (c) =>
            c.name.trim() &&
            cardKeywords(c) &&
            (opts.ids ? opts.ids.includes(c.id) : !isParsed(c))
        );
        if (!todo.length || get().parsingCast) return null;
        const origin = get()._originId();
        set({ parsingCast: true });
        try {
          const data = await parseComicCharacters({
            engine: ai.engine,
            model: ai.model,
            cards: todo.map((c) => ({ name: c.name.trim(), keywords: cardKeywords(c) })),
            num_ctx: ai.numCtx,
            // 只是分類 tag：不開思考
            think: ai.engine === "ollama" || ai.engine === "strata" ? false : undefined,
          });
          const ids = new Set(todo.map((c) => c.id));
          const parsed = (cards) =>
            cards.map((c) => {
              const r = ids.has(c.id) && (data.cards || []).find((x) => sameName(x.name, c.name));
              if (!r) return c;
              return {
                ...c,
                keywords: cardKeywords(c),
                features: r.features || "",
                outfit: r.outfit || "",
                pose: r.pose || "",
                scene: r.scene || "",
                parsed_from: cardKeywords(c),
                lora: c.lora || (r.loras || []).join(", "),
              };
            });
          await get()._applyResult(origin, (proj) => ({ characters: parsed(proj.characters || []) }));
          return parsed;
        } finally {
          set({ parsingCast: false });
        }
      },

      // ---- AI 撰寫故事（分鏡的依據）----
      // 已有故事時是改寫：照 instruction 改；沒給意見就重寫一個不同的版本。標題空的話順便帶入。
      // 結果只寫回發起時的作品：途中換了作品就存到伺服器上的原作品並提示（見 _applyResult）。
      async writeStory({ engine, model, lang, numCtx, instruction = "" }) {
        const st = get();
        if (st.storyWriting || (!st.premise.trim() && !st.story.trim())) return;
        get()._namedCast(lang);
        const origin = get()._originId();
        const cards = get().characters;
        set({ storyWriting: true, notices: [] });
        try {
          const parsed = await get().parseCharacters({ engine, model, lang, numCtx });
          // 解析途中換了作品：用發起時那份的角色卡（套上解析結果），不拿目前開著的
          const cast = get().projectId === origin ? get().characters : parsed ? parsed(cards) : cards;
          const data = await writeComicStory({
            engine,
            model,
            premise: st.premise,
            panel_count: st.panelCount,
            characters: castPayload(cast),
            lang,
            system: st.systemPrompt,
            story: st.story,
            instruction,
            num_ctx: numCtx,
            think: engine === "ollama" || engine === "strata" ? st.think : undefined,
          });
          const local = await get()._applyResult(origin, (proj) => ({
            story: data.story || "",
            ...(!(proj.title || "").trim() && data.title ? { title: data.title } : {}),
          }));
          if (local) set({ notices: Array.isArray(data.notices) ? data.notices : [] });
        } finally {
          set({ storyWriting: false });
        }
      },

      // ---- 依故事生成分鏡 ----
      // 結果只寫回發起時的作品：途中換了作品就存到伺服器上的原作品（原本的分鏡先存成一版）並提示。
      async generateStoryboard({ engine, model, lang, numCtx }) {
        const { premise, story, panelCount, style, systemPrompt, systemBase, think, skills, promptMode } =
          get();
        if (!story.trim() || get().storyboarding) return;
        get()._namedCast(lang);
        const origin = get()._originId();
        const cards = get().characters;
        const checkpoint = get().settings.sd_model_checkpoint || "";
        // 模型回的名字對回卡片上的寫法（後端已做過一次；這裡再保險，對不上的原樣保留）
        const canon = (list, names) => {
          const cast = list.filter((c) => (c.name || "").trim());
          const out = [];
          for (const n of Array.isArray(names) ? names : []) {
            const v = findCard(cast, n)?.name ?? n;
            if (v && !hasName(out, v)) out.push(v);
          }
          return out;
        };
        set({ storyboarding: true, notices: [] });
        try {
          const parsed = await get().parseCharacters({ engine, model, lang, numCtx });
          const all = get().projectId === origin ? get().characters : parsed ? parsed(cards) : cards;
          const cast = all.filter((c) => c.name.trim());
          const data = await generateStoryboard({
            engine,
            model,
            premise,
            story,
            panel_count: panelCount,
            characters: castPayload(cast),
            style,
            lang,
            num_ctx: numCtx,
            think: engine === "ollama" || engine === "strata" ? think : undefined,
            system: systemPrompt,
            system_base: systemBase,
            skills,
            prompt_mode: promptMode,
            checkpoint,
          });
          const local = await get()._applyResult(
            origin,
            (proj) => ({
              panels: (data.panels || []).map((p) =>
                newPanel({
                  beat: p.beat || "",
                  prompt: p.prompt || "",
                  description: p.description || "",
                  expression: p.expression || "",
                  characters: canon(proj.characters || [], p.characters),
                  looks: panelLooks(p),
                  bubbles: bubblesFromScript(p.dialogue, p.caption),
                })
              ),
              panelsStory: story, // 這組分鏡依據的故事（之後改了故事再分鏡，存版本時用它）
            }),
            { snapshot: true }
          );
          if (local) set({ notices: Array.isArray(data.notices) ? data.notices : [] });
        } finally {
          set({ storyboarding: false });
        }
      },

      // ---- 單格：重新生成關鍵字 ----
      // 把整份分鏡（含各格對白 / 旁白）當前後文送給模型，只換這一格的場景 tag 與表情；
      // 對白氣泡、出場角色不動。重生前的關鍵字留在 promptUndo，可一鍵復原。
      async regeneratePrompt(id, instruction, { engine, model, lang, numCtx }) {
        const st = get();
        const index = st.panels.findIndex((p) => p.id === id);
        if (index < 0 || st.promptBusy[id]) return;
        const origin = get()._originId();
        set({
          promptBusy: { ...st.promptBusy, [id]: true },
          promptError: { ...st.promptError, [id]: "" },
        });
        try {
          const data = await regeneratePanelPrompt({
            engine,
            model,
            index,
            instruction: instruction || "",
            panels: st.panels.map(panelScript),
            premise: st.premise,
            story: st.story,
            characters: castPayload(st.characters),
            style: st.style,
            lang,
            num_ctx: numCtx,
            think: engine === "ollama" || engine === "strata" ? st.think : undefined,
            system: st.systemPrompt,
            skills: st.skills,
            prompt_mode: st.promptMode,
            checkpoint: st.settings.sd_model_checkpoint || "",
          });
          // 只寫回發起時的作品（途中換了作品就存到伺服器上的原作品，見 _applyResult）
          let cur = null;
          const local = await get()._applyResult(origin, (proj) =>
            patchPanel(proj, id, (p) => {
              cur = p;
              return {
                prompt: data.prompt || p.prompt,
                expression: data.expression || p.expression,
                // 這次判定只寫標籤（非 Anima）就清掉舊句子，讓這格和新的標籤一致；復原可換回
                description: data.sentences ? data.description || p.description || "" : "",
                // 角色卡解析過時，重寫也會調整各角色這格的姿勢、服裝、特徵
                ...(data.looks && typeof data.looks === "object" ? { looks: data.looks, outfits: undefined } : {}),
              };
            })
          );
          if (!local || !cur) return;
          set({
            promptUndo: {
              ...get().promptUndo,
              [id]: {
                prompt: cur.prompt,
                expression: cur.expression,
                description: cur.description || "",
                looks: panelLooks(cur),
              },
            },
          });
          if (Array.isArray(data.notices) && data.notices.length) set({ notices: data.notices });
        } catch (e) {
          set({ promptError: { ...get().promptError, [id]: e.message || "failed" } });
        } finally {
          set({ promptBusy: { ...get().promptBusy, [id]: false } });
        }
      },
      undoPrompt(id) {
        const u = get().promptUndo[id];
        const cur = get().panels.find((p) => p.id === id);
        if (!u || !cur) return;
        set({
          promptUndo: {
            ...get().promptUndo,
            [id]: {
              prompt: cur.prompt,
              expression: cur.expression,
              description: cur.description || "",
              looks: panelLooks(cur),
            },
          },
        });
        get().setPanel(id, {
          prompt: u.prompt,
          expression: u.expression,
          description: u.description || "",
          looks: panelLooks(u),
          outfits: undefined,
        });
      },

      // ---- 分鏡版本 ----
      // label：auto（AI 生成分鏡前）| import（匯入腳本前）| beforeRestore（回復前）| manual（手動）
      // 同步建立快照並放進本機快取，接著送到伺服器；伺服器失敗就留在快取標 pending，之後補送。
      snapshotPanels(label = "manual") {
        const st = get();
        if (!st.panels.length) return null;
        const story = versionStory(st, label);
        const json = JSON.stringify(st.panels);
        if (st.versions.some((v) => v.panels && JSON.stringify(v.panels) === json && (v.story || "") === story))
          return null;
        const pid = get()._originId(); // 版本掛在作品 id 下；作品本身由自動儲存補上
        const version = makeVersion(st.panels, { label, premise: st.premise, story });
        set({ versions: [{ ...version, pending: true }, ...st.versions].slice(0, VERSION_CACHE) });
        return get().pushVersion(version, pid);
      },
      // pid：版本屬於哪份作品（送出時就決定，途中換了作品也不會存到別份）。
      // 作品還沒存上去過、已在別處刪除、或在這個分頁刪掉時不送（後端也會拒絕），版本留在本機快取標
      // pending：存上去 / 另存成新作品後由 flushVersions 補送到那個 id，選「捨棄」就跟著丟掉。
      async pushVersion(version, pid = get().projectId) {
        const st = get();
        if (_deleted.has(pid) || (pid === st.projectId && (st.remoteGone || !st.savedAt))) return null;
        try {
          const r = await addComicVersion(pid, version);
          set((st) => ({
            versions: r.duplicate
              ? st.versions.filter((v) => v.id !== version.id) // 伺服器已有一模一樣的版本
              : st.versions.map((v) => (v.id === version.id ? { ...v, pending: false } : v)),
          }));
          return r;
        } catch {
          return null;
        }
      },
      async flushVersions() {
        const pid = get().projectId;
        if (get().remoteGone) return; // 已在別處刪除：等另存成新作品後再送
        for (const v of get().versions.filter((x) => x.pending && x.panels)) {
          if (get().projectId !== pid) return; // 換了作品：剩下的是原作品的，下次開它存好時再補
          await get().pushVersion({ ...v, pending: undefined }, pid);
        }
      },
      // 版本清單：伺服器的完整歷史（摘要）；取不到、或作品已在別處刪除時用本機快取
      async listVersions() {
        const id = get().projectId;
        if (!id || get().remoteGone) return get().versions.map(versionSummary);
        try {
          return await listComicVersions(id);
        } catch {
          return get().versions.map(versionSummary);
        }
      },
      // 整份版本（含分鏡格）：快取有就用，沒有再向伺服器取
      async getVersion(id) {
        const cached = get().versions.find((v) => v.id === id);
        const v = cached?.panels ? cached : await getComicVersion(get().projectId, id);
        // 伺服器上的版本可能是手做 / 很舊的資料：格子補齊欄位（預覽和回復都用這份）
        return v && { ...v, panels: (Array.isArray(v.panels) ? v.panels : []).map(normPanel).filter(Boolean) };
      },
      async restoreVersion(id) {
        const pid = get().projectId;
        const v = await get().getVersion(id);
        if (!v?.panels?.length || get().projectId !== pid) return; // 取版本的途中換了作品
        get().snapshotPanels("beforeRestore"); // 目前的也留一版，回復不會丟東西
        const story = typeof v.story === "string" && v.story.trim() ? v.story : "";
        set({
          panels: clone(v.panels).map((p) => ({
            ...p,
            status: p.image?.url ? "done" : "idle",
            error: "",
            check: isCheckBusy(p.check) ? null : p.check || null,
          })),
          // 那一版當時的故事（舊版本沒存故事就保留目前的）
          ...(story ? { story } : {}),
          panelsStory: story,
          view: "grid",
        });
      },
      async deleteVersion(id) {
        set((st) => ({ versions: st.versions.filter((v) => v.id !== id) }));
        if (get().projectId) await deleteComicVersionRemote(get().projectId, id).catch(() => {});
      },

      // ---- 出圖 ----
      // 出圖 → 看圖檢查；不符合就依檢查意見重寫這格關鍵字再畫，最多 MAX_AUTO_FIX 次，
      // 還不符合就標「待人工確認」。種子照「鎖定種子」：鎖定時同一個，不鎖定時每次隨機。
      // 途中換了作品就停（出好的圖由 _renderPanel 存回原作品）。
      async generatePanel(id) {
        if (!get().panels.some((p) => p.id === id)) return;
        const ai = aiOptions(get().settings);
        const origin = get()._originId();
        get().setPanel(id, { check: null });
        for (let attempts = 0; ; ) {
          if (!(await get()._renderPanel(id))) return;
          get().setPanel(id, { check: { status: "checking", attempts, problems: [] } });
          let res;
          try {
            res = await get().checkPanel(id, ai);
            if (get().projectId !== origin) return; // 檢查途中換了作品：結果不寫到別份
          } catch (e) {
            get().setPanel(id, {
              check: { status: "error", attempts, problems: [e.message || "failed"] },
            });
            return;
          }
          if (Array.isArray(res.notices) && res.notices.length) set({ notices: res.notices });
          const problems = res.problems || [];
          if (res.status !== "fail") {
            get().setPanel(id, {
              check: { status: res.status, attempts, problems, reason: res.reason || "" },
            });
            return;
          }
          if (attempts >= MAX_AUTO_FIX) {
            get().setPanel(id, { check: { status: "gave_up", attempts, problems, fix: res.fix || "" } });
            return;
          }
          attempts += 1;
          get().setPanel(id, { check: { status: "fixing", attempts, problems, fix: res.fix || "" } });
          await get().regeneratePrompt(id, res.fix, ai);
          const err = get().promptError[id];
          if (err) {
            get().setPanel(id, { check: { status: "gave_up", attempts, problems: [...problems, err] } });
            return;
          }
        }
      },

      // 只出圖（不檢查）；成功且還開著同一份作品回 true。
      // 出圖途中換了作品：圖存回伺服器上的原作品那格（見 _applyResult），回 false。
      async _renderPanel(id) {
        const panel = get().panels.find((p) => p.id === id);
        if (!panel) return false;
        const prompt = get().composePrompt(panel);
        if (!prompt.trim()) {
          get().setPanel(id, { status: "error", error: "empty prompt" });
          return false;
        }
        const origin = get()._originId();
        get().setPanel(id, { status: "generating", error: "" });
        try {
          const r = await generateImage(prompt, get().composeImageSettings());
          return await get()._applyResult(origin, (proj) =>
            patchPanel(proj, id, {
              status: "done",
              error: "",
              image: { url: r.url, params: r.params, info: r.info || "" },
              seed: r.seed ?? r.params?.seed, // 實際用到的（不鎖定時送 -1，A1111 抽的那個）
            })
          );
        } catch (e) {
          get().setPanel(id, { status: "error", error: e.message || "failed" });
          return false;
        }
      },

      // 讓視覺模型看這格的圖，對照 beat（沒有就用格子內容加劇情大綱）判斷有沒有演對故事
      async checkPanel(id, ai = aiOptions(get().settings)) {
        const st = get();
        const index = st.panels.findIndex((p) => p.id === id);
        const panel = st.panels[index];
        if (!panel?.image?.url) return { status: "skipped", problems: [], reason: "no image" };
        return checkComicPanel({
          engine: ai.engine,
          model: ai.checkModel,
          panels: st.panels.map(panelScript),
          index,
          image: panel.image.url,
          story: st.story,
          premise: st.premise,
          characters: castPayload(st.characters),
          lang: ai.lang,
          num_ctx: ai.numCtx,
          // 只是判斷符不符合：不開思考，免得每格都要等很久
          think: ai.engine === "ollama" || ai.engine === "strata" ? false : undefined,
        });
      },

      // 逐格生成（A1111 一次只能跑一張，序列化避免互相排隊卡住 UI 進度）
      async generateAll() {
        const ids = get().panels.map((p) => p.id);
        if (!ids.length || get().genProgress) return;
        const origin = get()._originId();
        // 鎖定種子時先固定一次，確保全部用同一個
        get()._resolvedSeed();
        set({ genProgress: { done: 0, total: ids.length } });
        try {
          for (let i = 0; i < ids.length; i++) {
            if (get().projectId !== origin) break; // 換了作品：剩下的格子不再畫
            await get().generatePanel(ids[i]);
            set({ genProgress: { done: i + 1, total: ids.length } });
          }
        } finally {
          set({ genProgress: null });
        }
      },

      // 頁面重新載入 / 從伺服器開啟作品時，「生成中」只是上次關頁前存下的瞬間狀態，
      // 沒有任何工作在跑：改回 idle（有圖的是 done），格子的生成鈕才按得下去
      settlePanels() {
        if (!get().panels.some((p) => p.status === "generating" || isCheckBusy(p.check))) return;
        set((st) => ({
          panels: st.panels.map((p) => ({
            ...p,
            ...(p.status === "generating"
              ? { status: p.image?.url ? "done" : "idle", error: "" }
              : {}),
            ...(isCheckBusy(p.check) ? { check: null } : {}),
          })),
        }));
      },

      // 由「圖片說故事」等外部來源匯入整份腳本（角色卡 + 分鏡格）：一律建立一份新作品（新的
      // projectId），原本開著的作品一個欄位都不動。換之前先把目前作品待存的修改存好（存不上去丟
      // code="unsaved"，畫面問過使用者後可帶 { discard: true }）。出圖設定、畫風品質詞、負面提示詞、
      // 額外指示等沿用目前作品的；版本快取從空的開始。匯入後馬上存一次，作品庫就看得到。
      // panels 為空時只帶入標題與故事（例如把生成的故事當劇情，之後再按「依故事生成分鏡」）。
      async importScript(
        { title = "", premise = "", story = "", style = "", characters = [], panels = [] },
        opts = {}
      ) {
        const cast = (characters || [])
          .filter((c) => (c?.name || "").trim())
          .map((c) => ({
            ...newCharacter(),
            name: c.name.trim(),
            keywords: c.appearance || "", // 圖片說故事推得的外觀 tag 當角色關鍵字，下次寫故事 / 分鏡時解析
          }));
        const names = cast.map((c) => c.name);
        await get()._switchProject(async () => {
          // 畫風：保留既有的品質詞，把推得的畫風接在後面（重複 tag 由 composePrompt 去重）
          const cur = (get().style || "").trim().replace(/[,，\s]*$/, "");
          const extra = (style || "").trim();
          const mergedStyle =
            extra && !cur.toLowerCase().includes(extra.toLowerCase())
              ? cur
                ? `${cur}, ${extra}`
                : extra
              : cur;
          set({ _loading: true });
          set({
            projectId: uid(),
            pageUrl: "",
            savedAt: null,
            saveState: "idle",
            versions: [],
            dirty: true,
            remoteGone: false,
            notices: [],
            title: title || "",
            premise: premise || "",
            story: story || "",
            panelsStory: story || "",
            style: mergedStyle,
            characters: cast,
            panels: (panels || []).map((p) =>
              newPanel({
                beat: p.beat || "",
                prompt: p.prompt || "",
                description: p.description || "",
                expression: p.expression || "",
                characters: (p.characters || [])
                  .map((n) => names.find((m) => sameName(m, n)))
                  .filter((n, i, arr) => n && arr.indexOf(n) === i),
                bubbles: bubblesFromScript(p.dialogue, p.caption),
                // 「圖片分鏡」：上傳圖已存在後端，直接當這格的圖（不必出圖；重新生成會覆蓋）
                image: p.image_url ? { url: p.image_url, params: null, info: "" } : null,
                status: p.image_url ? "done" : "idle",
              })
            ),
            view: "grid",
          });
          set({ _loading: false });
        }, opts);
        await get().saveProject();
      },

      reset() {
        set({
          title: "",
          premise: "",
          story: "",
          systemPrompt: "",
          systemBase: "",
          skills: [],
          promptMode: "auto",
          panelCount: 6,
          style: "masterpiece, best quality, amazing quality",
          negative:
            "lowres, bad anatomy, worst quality, bad hands, text, watermark",
          characters: [],
          settings: { ...DEFAULT_SETTINGS },
          layout: { ...DEFAULT_LAYOUT },
          panels: [],
          panelsStory: "",
          versions: [],
          view: "grid",
        });
      },

      // ---- 伺服器端作品：自動儲存 / 作品庫 ----
      // 分鏡、角色卡、出圖結果等一有變動就（debounce）整份 PUT 到後端，存進 DATA_DIR 的
      // SQLite；圖片本來就在圖片目錄。重啟容器、清瀏覽器資料、換裝置都還在。
      // 同一時間只送一個 PUT：前一個還沒回來就排在它後面，舊內容不會後到蓋掉新內容。
      async saveProject() {
        const run = (_saving || Promise.resolve()).catch(() => {}).then(() => get()._putProject());
        _saving = run;
        try {
          await run;
        } finally {
          if (_saving === run) _saving = null;
        }
      },
      async _putProject() {
        const st = get();
        if (st._loading) return;
        let id = st.projectId;
        if (!id) {
          if (projectIsEmpty(st)) {
            if (st.dirty) set({ dirty: false }); // 全空的工作區不建作品，也沒有要存的
            return;
          }
          id = uid();
          set({ projectId: id });
        }
        if (_deleted.has(id)) {
          cancelRetry();
          set({ dirty: false }); // 這個分頁剛刪掉的作品：不存回去
          return;
        }
        if (st.remoteGone) return; // 已在別處刪除：等使用者決定，不建回來
        const seq = _editSeq;
        clearTimeout(_retryTimer); // 這次就是在存了；失敗再排下一次
        _retryTimer = null;
        set({ saveState: "saving" });
        try {
          // 存上去過的作品先確認伺服器上還在：在別處刪除了就不建回來（PUT 會整份新建）。
          // 只有從沒存上去過的新作品（savedAt 是空的）可以直接建立。
          if (get().savedAt) {
            try {
              await getComic(id);
            } catch (e) {
              if (e?.status !== 404) throw e;
              get()._markRemoteGone(id);
              return;
            }
          }
          const saved = await putComic({ id, ...pickProject(get()) });
          if (get().projectId !== id) return;
          _retryStep = 0;
          // 存的途中又改過：還不算存好（計時器會再存一次）
          set({ savedAt: saved.updated_at, saveState: "saved", ...(seq === _editSeq ? { dirty: false } : {}) });
          get().flushVersions();
        } catch {
          if (get().projectId !== id) return;
          set({ saveState: "error" });
          scheduleRetry(id);
        }
      },
      // 把目前作品待存的修改馬上存好（換作品前用）；存好或本來就沒有待存的回 true
      async _flushSave() {
        clearTimeout(_saveTimer);
        _saveTimer = null;
        if (_saving) await _saving.catch(() => {});
        // 存的途中又有修改（例如 AI 的結果剛好回來）就再存一次
        for (let i = 0; i < 3 && get().dirty; i++) {
          await get().saveProject();
          if (get().saveState === "error") break;
        }
        return !get().dirty;
      },
      // 換到別的作品（開作品 / 新作品 / 匯入都走這裡）：先把目前作品待存的修改存好再換。
      // 存不上去就不換、丟出 code="unsaved" 的錯誤；畫面問過使用者後可帶 { discard: true } 再呼叫
      // （不存、直接換；刪除目前作品、或本機修改已另存時也用它）。
      async _switchProject(load, { discard = false } = {}) {
        while (_switching) await _switching.catch(() => {});
        const run = (async () => {
          if (!discard && !(await get()._flushSave()))
            throw Object.assign(unsavedError(), { gone: get().remoteGone }); // gone：存不上去是因為已在別處刪除
          cancelRetry(); // 換作品後不再重試舊作品
          clearTimeout(_saveTimer);
          _saveTimer = null;
          if (_saving) await _saving.catch(() => {});
          await _remote.catch(() => {}); // 寫回原作品的結果做完，開到的才是新的
          await load();
        })();
        _switching = run;
        try {
          await run;
        } finally {
          if (_switching === run) _switching = null;
        }
      },
      // 非同步步驟發起時先確定作品 id：結果回來時才知道要寫回哪一份
      _originId() {
        let id = get().projectId;
        if (!id) {
          id = uid();
          set({ projectId: id, ...(projectIsEmpty(get()) ? {} : { dirty: true }) });
        }
        return id;
      },
      // 非同步步驟（寫故事、分鏡、解析角色、單格重寫關鍵字、出圖）的結果只寫回「發起時的作品」：
      // 還開著同一份就直接改；已經換到別的作品，就改伺服器上原作品那份（目前開著的作品不動、
      // 也不替它存版本），並在畫面上提示。原作品已刪除或存不上去就丟棄並提示。
      // patch(作品)：由作品內容算出要改的欄位，回 null＝不用改；snapshot：改分鏡前先把原本的存成一版。
      // 回傳 true＝改在目前開著的作品上。
      async _applyResult(origin, patch, { snapshot = false } = {}) {
        while (_switching) await _switching.catch(() => {});
        if (get().projectId === origin) {
          const change = patch(get());
          if (change) {
            if (snapshot) get().snapshotPanels("auto");
            set(change);
          }
          return true;
        }
        const job = _remote
          .catch(() => {})
          .then(async () => {
            if (_deleted.has(origin)) throw new Error("deleted");
            const data = normalizeProject(await getComic(origin));
            const change = patch(data);
            if (change) {
              if (snapshot && Array.isArray(data.panels) && data.panels.length) {
                const v = makeVersion(data.panels, {
                  label: "auto",
                  premise: data.premise,
                  story: versionStory(data, "auto"),
                });
                await addComicVersion(origin, v).catch(() => {});
              }
              await putComic({ ...data, ...change, id: origin });
            }
            return data.title || "";
          });
        _remote = job;
        try {
          get()._notice({ code: "saved_to_origin", title: await job });
        } catch {
          get()._notice({ code: "result_dropped" });
        }
        return false;
      },
      // 畫面提示（同一種、同一份作品的只留一則）
      _notice(n) {
        set((st) => ({
          notices: [...st.notices.filter((x) => !(x.code === n.code && x.title === n.title)), n],
        }));
      },
      // 目前作品已在別處刪除：停止自動儲存與重試，畫面提示（本機修改留著）
      _markRemoteGone(id) {
        if (get().projectId !== id) return;
        cancelRetry();
        clearTimeout(_saveTimer);
        _saveTimer = null;
        set({ remoteGone: true, saveState: "gone" });
      },
      // 已在別處刪除的作品：本機這份另存成新作品（新 id；本機快取的版本也一起補送到新作品）
      async keepAsNewProject() {
        if (!get().remoteGone) return;
        set({
          projectId: uid(),
          savedAt: null,
          remoteGone: false,
          saveState: "idle",
          dirty: true,
          versions: get().versions.map((v) => ({ ...v, pending: !!v.panels })),
        });
        await get().saveProject();
      },
      async listProjects() {
        return listComics();
      },
      async openProject(id, opts = {}) {
        await get()._switchProject(async () => {
          set({ _loading: true });
          try {
            const data = await getComic(id);
            get().reset(); // 也清掉上一份作品的版本快取
            set({
              ...pickProject(normalizeProject({ ...get(), ...data })),
              projectId: id,
              savedAt: data.updated_at || null,
              saveState: "saved",
              dirty: false,
              remoteGone: false,
              view: "grid",
            });
            get().settlePanels();
          } finally {
            set({ _loading: false });
          }
        }, opts);
      },
      async newProject(opts = {}) {
        await get()._switchProject(async () => {
          set({ _loading: true });
          get().reset();
          set({ projectId: null, pageUrl: "", savedAt: null, saveState: "idle", dirty: false, remoteGone: false });
          set({ _loading: false });
        }, opts);
      },
      async deleteProject(id) {
        _deleted.add(id);
        const current = get().projectId === id;
        const retrying = current && _retryTimer !== null;
        const step = _retryStep;
        const pending = current && _saveTimer !== null;
        if (current) {
          cancelRetry();
          clearTimeout(_saveTimer);
          _saveTimer = null;
          if (_saving) await _saving.catch(() => {});
        }
        try {
          await deleteComicRemote(id);
        } catch (e) {
          _deleted.delete(id);
          // 沒刪成、還開著這份：恢復刪除前的自動儲存 / 重試（有待存的修改才需要）
          if (get().projectId === id && get().dirty) {
            if (retrying || get().saveState === "error") {
              _retryStep = Math.max(0, step - 1);
              scheduleRetry(id);
            } else if (pending) armAutosave();
          }
          throw e;
        }
        if (get().projectId === id) await get().newProject({ discard: true });
      },
      // 進入頁面時對一次伺服器：
      // - 別的裝置改得比較新就用伺服器的；本機這時也有沒存上去的修改，就先把本機這份另存成
      //   一份新作品（標題加註）再載入，兩邊都不丟，並在畫面上提示。
      // - 伺服器沒有比較新、本機有沒存上去的修改（存檔失敗、存到一半、計時器還沒到就關頁）：
      //   馬上存上去，存成功才顯示「已儲存」。
      // - 伺服器沒有：存上去過的＝在別處刪除，不建回來、提示；從沒存上去過的新作品才建立。
      syncProject() {
        if (!_syncing) _syncing = get()._syncProject().finally(() => (_syncing = null));
        return _syncing;
      },
      async _syncProject() {
        const wasDirty = get().dirty;
        const local = pickProject(get()); // 整理「生成中」之前的內容（跟伺服器比對用）
        get().settlePanels();
        const seq = _editSeq;
        if (_switching) return; // 換作品中：換的那邊會把作品載好、存好
        if (_saving) await _saving.catch(() => {});
        const { projectId, savedAt } = get();
        if (!projectId) {
          if (get().dirty) await get().saveProject();
          return;
        }
        let data;
        try {
          data = await getComic(projectId);
        } catch (e) {
          if (e?.status === 404) {
            // 存上去過、現在不在了＝在別處刪除：不建回來，提示；從沒存上去過的新作品才建立
            if (_deleted.has(projectId)) return;
            if (savedAt) get()._markRemoteGone(projectId);
            else get().saveProject();
          } else if (get().dirty && get().projectId === projectId) {
            // 連不上伺服器、本機又有沒存上去的修改：標成失敗，稍後再對一次
            set({ saveState: "error" });
            scheduleRetry(projectId, "sync");
          }
          return;
        }
        if (get().projectId !== projectId || _switching) return;
        if ((data.updated_at || 0) > (savedAt || 0) + 1) {
          const edited = _editSeq !== seq; // 對伺服器的途中又改了
          if (!wasDirty && !edited) {
            await get().openProject(projectId, { discard: true });
            return;
          }
          const mine = edited ? pickProject(get()) : local;
          if (!sameProject(normalizeProject(data), mine)) {
            const title = comicT("localCopyTitle", { title: mine.title || comicT("untitled") });
            try {
              await putComic({ ...mine, id: uid(), title });
            } catch {
              set({ saveState: "error" }); // 另存不了就先不換，本機修改留著，下次再試
              return;
            }
            await get().openProject(projectId, { discard: true });
            get()._notice({ code: "local_copy", title });
            return;
          }
          // 伺服器那份就是本機這份（上次存到一半就關頁，其實已經存上去了）
          set({ savedAt: data.updated_at });
        }
        if (get().dirty) await get()._flushSave();
        else set({ saveState: "saved", savedAt: data.updated_at || savedAt });
      },
      // 匯出整頁 PNG 後，同一張圖也存進圖片目錄並記在作品上（作品庫縮圖）
      async savePage(dataUrl) {
        if (!dataUrl) return;
        if (!get().projectId) await get().saveProject();
        const id = get().projectId;
        if (!id) return;
        const { url } = await saveComicPage(id, dataUrl);
        if (get().projectId === id) set({ pageUrl: url }); // 存的途中換了作品：後端已記在原作品上
      },
    }),
    {
      name: "webui-comic",
      storage: createJSONStorage(() => localStorage),
      // 瀏覽器裡存的作品也可能少欄位（手做 / 很舊的資料）：還原時補齊
      merge: (persisted, current) => {
        const st = { ...current, ...(isObj(persisted) ? persisted : {}) };
        return { ...st, ...pickProject(normalizeProject(st)) };
      },
      // 不持久化執行期旗標
      partialize: (st) => ({
        title: st.title,
        premise: st.premise,
        story: st.story,
        systemPrompt: st.systemPrompt,
        systemBase: st.systemBase,
        skills: st.skills,
        promptMode: st.promptMode,
        panelCount: st.panelCount,
        think: st.think,
        style: st.style,
        negative: st.negative,
        characters: st.characters,
        settings: st.settings,
        layout: st.layout,
        panels: st.panels,
        panelsStory: st.panelsStory,
        view: st.view,
        projectId: st.projectId,
        pageUrl: st.pageUrl,
        versions: st.versions,
        savedAt: st.savedAt,
        dirty: st.dirty,
      }),
    }
  )
);

// 自動儲存：作品欄位任一變動就標成未存（dirty），debounce 後整份存到伺服器
useComic.subscribe((st, prev) => {
  if (st._loading) return;
  if (!PROJECT_KEYS.some((k) => st[k] !== prev[k])) return;
  if (!st.projectId && projectIsEmpty(st)) return;
  _editSeq += 1;
  if (!st.dirty) useComic.setState({ dirty: true });
  armAutosave();
});
