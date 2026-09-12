// 漫畫工作室狀態：劇本、角色卡、分鏡格、出圖設定、對白氣泡。
// 出圖重用 lib/api.js 的 generateImage（txt2img）；分鏡用 lib/comicApi.js。
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
import { generateStoryboard, regeneratePanelPrompt } from "../lib/comicApi";
import { isExpressionTag, splitTags, tagKey } from "../comic/expressionTags";
import { defaultTail } from "../comic/bubbleShape";
import { autoName, findCard, hasName, sameName } from "../comic/names";

// 作品內容（會存到伺服器的欄位）；這些欄位任一變動就 debounce 自動儲存
const PROJECT_KEYS = [
  "title",
  "premise",
  "systemPrompt",
  "systemBase",
  "panelCount",
  "think",
  "style",
  "negative",
  "characters",
  "settings",
  "layout",
  "panels",
  "pageUrl",
];
const AUTOSAVE_MS = 1500;
// 分鏡版本：整份歷史存在伺服器（不設上限）；瀏覽器只快取最近幾版（含分鏡格內容），
// 更早的版本預覽 / 回復時再向伺服器取
const VERSION_CACHE = 5;
const clone = (v) => JSON.parse(JSON.stringify(v));
const versionSummary = ({ panels, pending, ...rest }) => rest;

const pickProject = (st) => Object.fromEntries(PROJECT_KEYS.map((k) => [k, st[k]]));
const projectIsEmpty = (st) =>
  !st.panels.length && !st.premise.trim() && !st.title.trim() && !st.characters.length;

// 每格「表情」在提示詞裡的強調權重：放在畫風之後、角色固定 tag 之前，
// 並用 (…:1.2) 加權，否則會被角色卡 20 幾個固定 tag 與 LoRA 壓過去而每格同一張臉。
const EXPRESSION_WEIGHT = 1.2;

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
  seed: -1, // -1＝首次生成時抽一個固定下來（鎖定時跨格共用）
};

const DEFAULT_LAYOUT = { columns: 2, gutter: 14, bg: "#f5f5f4" };

const newCharacter = () => ({ id: uid(), name: "", appearance: "", lora: "" });

const newPanel = (patch = {}) => ({
  id: uid(),
  prompt: "",
  expression: "", // 該格表情（danbooru tag，逗號分隔）；獨立於場景 prompt
  characters: [],
  bubbles: [],
  image: null, // {url, params, info}
  status: "idle", // idle | generating | done | error
  error: "",
  seed: null, // 實際用到的 seed（出圖後回填）
  ...patch,
});

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
      systemPrompt: "", // 額外指示，接在 system 範本之後（指引 AI 分鏡）
      systemBase: "", // 覆寫內建分鏡 system 範本；空＝用預設
      panelCount: 6,
      style: "masterpiece, best quality, amazing quality",
      negative: "lowres, bad anatomy, worst quality, bad hands, text, watermark",
      characters: [],
      settings: { ...DEFAULT_SETTINGS },
      layout: { ...DEFAULT_LAYOUT },
      panels: [],
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
      _loading: false, // 從伺服器載入中（避免觸發自動儲存）

      // ---- 執行期（不持久化）----
      storyboarding: false,
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
      // 順序：畫風 → (表情:1.2) → 角色外觀 / LoRA（濾掉表情類 tag）→ 場景。
      // 全程依 tag 去重（外觀與 LoRA 觸發詞常重複；場景若又寫了畫風詞也會被吃掉）。
      composePrompt(panel) {
        const { characters, style } = get();
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
        const charTags = present.flatMap((c) =>
          take(splitTags(`${c.appearance || ""}, ${c.lora || ""}`), {
            dropExpression: true,
          })
        );
        const sceneTags = take(splitTags(panel.prompt));

        const parts = [
          styleTags.join(", "),
          exprTags.length
            ? `(${exprTags.join(", ")}:${EXPRESSION_WEIGHT})`
            : "",
          charTags.join(", "),
          sceneTags.join(", "),
        ].filter(Boolean);
        return parts.join(", ");
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

      // ---- AI 生成分鏡 ----
      async generateStoryboard({ engine, model, lang, numCtx }) {
        const { premise, panelCount, style, systemPrompt, systemBase, think } = get();
        if (!premise.trim() || get().storyboarding) return;
        // 沒填名字但有外觀 / LoRA 的角色卡：自動命名，分鏡才引用得到、出圖才帶得進去
        let characters = get().characters;
        let counter = 0;
        const named = characters.map((c) => {
          if (c.name.trim() || !((c.appearance || "").trim() || (c.lora || "").trim())) return c;
          let name;
          do {
            name = autoName(++counter, lang);
          } while (characters.some((o) => sameName(o.name, name)));
          return { ...c, name };
        });
        if (named.some((c, i) => c !== characters[i])) {
          characters = named;
          set({ characters });
        }
        const cast = characters.filter((c) => c.name.trim());
        // 模型回的名字對回卡片上的寫法（後端已做過一次；這裡再保險，對不上的原樣保留）
        const canon = (names) => {
          const out = [];
          for (const n of Array.isArray(names) ? names : []) {
            const v = findCard(cast, n)?.name ?? n;
            if (v && !hasName(out, v)) out.push(v);
          }
          return out;
        };
        set({ storyboarding: true, notices: [] });
        try {
          const data = await generateStoryboard({
            engine,
            model,
            premise,
            panel_count: panelCount,
            characters: cast.map((c) => ({ name: c.name.trim(), appearance: c.appearance })),
            style,
            lang,
            num_ctx: numCtx,
            think: engine === "ollama" ? think : undefined,
            system: systemPrompt,
            system_base: systemBase,
          });
          const panels = (data.panels || []).map((p) =>
            newPanel({
              prompt: p.prompt || "",
              expression: p.expression || "",
              characters: canon(p.characters),
              bubbles: bubblesFromScript(p.dialogue, p.caption),
            })
          );
          get().snapshotPanels("auto");
          set({ panels, notices: Array.isArray(data.notices) ? data.notices : [] });
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
            panels: st.panels.map((p) => ({
              prompt: p.prompt,
              expression: p.expression,
              characters: p.characters,
              dialogue: (p.bubbles || [])
                .filter((b) => b.type !== "caption" && (b.text || "").trim())
                .map((b) => ({ speaker: b.speaker || "", text: b.text })),
              caption: (p.bubbles || []).find((b) => b.type === "caption")?.text || "",
            })),
            premise: st.premise,
            characters: st.characters
              .filter((c) => c.name.trim())
              .map((c) => ({ name: c.name.trim(), appearance: c.appearance })),
            style: st.style,
            lang,
            num_ctx: numCtx,
            think: engine === "ollama" ? st.think : undefined,
            system: st.systemPrompt,
          });
          const cur = get().panels.find((p) => p.id === id);
          if (!cur) return;
          set({
            promptUndo: {
              ...get().promptUndo,
              [id]: { prompt: cur.prompt, expression: cur.expression },
            },
          });
          get().setPanel(id, {
            prompt: data.prompt || cur.prompt,
            expression: data.expression || cur.expression,
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
        set({ promptUndo: { ...get().promptUndo, [id]: { prompt: cur.prompt, expression: cur.expression } } });
        get().setPanel(id, { prompt: u.prompt, expression: u.expression });
      },

      // ---- 分鏡版本 ----
      // label：auto（AI 生成分鏡前）| import（匯入腳本前）| beforeRestore（回復前）| manual（手動）
      // 同步建立快照並放進本機快取，接著送到伺服器；伺服器失敗就留在快取標 pending，之後補送。
      snapshotPanels(label = "manual") {
        const st = get();
        if (!st.panels.length) return null;
        const json = JSON.stringify(st.panels);
        if (st.versions.some((v) => v.panels && JSON.stringify(v.panels) === json)) return null;
        if (!st.projectId) set({ projectId: uid() }); // 版本掛在作品 id 下；作品本身由自動儲存補上
        const version = {
          id: uid(),
          at: Date.now(),
          label,
          premise: st.premise,
          count: st.panels.length,
          images: st.panels.filter((p) => p.image?.url).length,
          cover: st.panels.find((p) => p.image?.url)?.image.url || "",
          panels: clone(st.panels),
        };
        set({ versions: [{ ...version, pending: true }, ...st.versions].slice(0, VERSION_CACHE) });
        return get().pushVersion(version);
      },
      async pushVersion(version) {
        try {
          const r = await addComicVersion(get().projectId, version);
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
        for (const v of get().versions.filter((x) => x.pending && x.panels)) {
          await get().pushVersion({ ...v, pending: undefined });
        }
      },
      // 版本清單：伺服器的完整歷史（摘要）；取不到就退回本機快取
      async listVersions() {
        const id = get().projectId;
        if (!id) return get().versions.map(versionSummary);
        try {
          return await listComicVersions(id);
        } catch {
          return get().versions.map(versionSummary);
        }
      },
      // 整份版本（含分鏡格）：快取有就用，沒有再向伺服器取
      async getVersion(id) {
        const cached = get().versions.find((v) => v.id === id);
        if (cached?.panels) return cached;
        return getComicVersion(get().projectId, id);
      },
      async restoreVersion(id) {
        const v = await get().getVersion(id);
        if (!v?.panels) return;
        get().snapshotPanels("beforeRestore"); // 目前的也留一版，回復不會丟東西
        set({
          panels: clone(v.panels).map((p) => ({
            ...p,
            status: p.image?.url ? "done" : "idle",
            error: "",
          })),
          view: "grid",
        });
      },
      async deleteVersion(id) {
        set((st) => ({ versions: st.versions.filter((v) => v.id !== id) }));
        if (get().projectId) await deleteComicVersionRemote(get().projectId, id).catch(() => {});
      },

      // ---- 出圖 ----
      async generatePanel(id) {
        const panel = get().panels.find((p) => p.id === id);
        if (!panel) return;
        const prompt = get().composePrompt(panel);
        if (!prompt.trim()) {
          get().setPanel(id, { status: "error", error: "empty prompt" });
          return;
        }
        get().setPanel(id, { status: "generating", error: "" });
        try {
          const r = await generateImage(prompt, get().composeImageSettings());
          get().setPanel(id, {
            status: "done",
            error: "",
            image: { url: r.url, params: r.params, info: r.info || "" },
            seed: r.params?.seed,
          });
        } catch (e) {
          get().setPanel(id, { status: "error", error: e.message || "failed" });
        }
      },

      // 逐格生成（A1111 一次只能跑一張，序列化避免互相排隊卡住 UI 進度）
      async generateAll() {
        const ids = get().panels.map((p) => p.id);
        if (!ids.length || get().genProgress) return;
        // 鎖定種子時先固定一次，確保全部用同一個
        get()._resolvedSeed();
        set({ genProgress: { done: 0, total: ids.length } });
        try {
          for (let i = 0; i < ids.length; i++) {
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
        if (!get().panels.some((p) => p.status === "generating")) return;
        set((st) => ({
          panels: st.panels.map((p) =>
            p.status === "generating"
              ? { ...p, status: p.image?.url ? "done" : "idle", error: "" }
              : p
          ),
        }));
      },

      // 由「圖片說故事」等外部來源匯入整份腳本（角色卡 + 分鏡格），覆蓋目前的角色與分鏡。
      // panels 為空時只帶入標題與劇情（例如把生成的故事當作劇情大綱，之後再按「AI 生成分鏡」）。
      importScript({ title = "", premise = "", style = "", characters = [], panels = [] }) {
        get().snapshotPanels("import");
        const cast = (characters || [])
          .filter((c) => (c?.name || "").trim())
          .map((c) => ({
            id: uid(),
            name: c.name.trim(),
            appearance: c.appearance || "",
            lora: "",
          }));
        const names = cast.map((c) => c.name);
        // 畫風：保留既有的品質詞，把推得的畫風接在後面（重複 tag 由 composePrompt 去重）
        const cur = (get().style || "").trim().replace(/[,，\s]*$/, "");
        const extra = (style || "").trim();
        const mergedStyle =
          extra && !cur.toLowerCase().includes(extra.toLowerCase())
            ? cur
              ? `${cur}, ${extra}`
              : extra
            : cur;
        set({
          title: title || "",
          premise: premise || "",
          style: mergedStyle,
          characters: cast,
          panels: (panels || []).map((p) =>
            newPanel({
              prompt: p.prompt || "",
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
      },

      reset() {
        set({
          title: "",
          premise: "",
          systemPrompt: "",
          systemBase: "",
          panelCount: 6,
          style: "masterpiece, best quality, amazing quality",
          negative:
            "lowres, bad anatomy, worst quality, bad hands, text, watermark",
          characters: [],
          settings: { ...DEFAULT_SETTINGS },
          layout: { ...DEFAULT_LAYOUT },
          panels: [],
          versions: [],
          view: "grid",
        });
      },

      // ---- 伺服器端作品：自動儲存 / 作品庫 ----
      // 分鏡、角色卡、出圖結果等一有變動就（debounce）整份 PUT 到後端，存進 DATA_DIR 的
      // SQLite；圖片本來就在圖片目錄。重啟容器、清瀏覽器資料、換裝置都還在。
      async saveProject() {
        const st = get();
        if (st._loading) return;
        let id = st.projectId;
        if (!id) {
          if (projectIsEmpty(st)) return; // 全空的工作區不建作品
          id = uid();
          set({ projectId: id });
        }
        set({ saveState: "saving" });
        try {
          const saved = await putComic({ id, ...pickProject(get()) });
          set({ savedAt: saved.updated_at, saveState: "saved" });
          get().flushVersions();
        } catch {
          set({ saveState: "error" });
        }
      },
      async listProjects() {
        return listComics();
      },
      async openProject(id) {
        set({ _loading: true });
        try {
          const data = await getComic(id);
          get().reset(); // 也清掉上一份作品的版本快取
          set({
            ...pickProject({ ...get(), ...data }),
            projectId: id,
            savedAt: data.updated_at || null,
            saveState: "saved",
            view: "grid",
          });
          get().settlePanels();
        } finally {
          set({ _loading: false });
        }
      },
      newProject() {
        get().reset();
        set({ projectId: null, pageUrl: "", savedAt: null, saveState: "idle" });
      },
      async deleteProject(id) {
        await deleteComicRemote(id);
        if (get().projectId === id) get().newProject();
      },
      // 進入頁面時對一次伺服器：別的裝置改得比較新就用伺服器的；伺服器沒有（資料被清）就重新存上去
      async syncProject() {
        get().settlePanels();
        const { projectId, savedAt } = get();
        if (!projectId) return;
        try {
          const data = await getComic(projectId);
          if ((data.updated_at || 0) > (savedAt || 0) + 1) await get().openProject(projectId);
          else set({ saveState: "saved", savedAt: data.updated_at || savedAt });
        } catch (e) {
          if (e?.status === 404) get().saveProject();
        }
      },
      // 匯出整頁 PNG 後，同一張圖也存進圖片目錄並記在作品上（作品庫縮圖）
      async savePage(dataUrl) {
        if (!dataUrl) return;
        if (!get().projectId) await get().saveProject();
        const id = get().projectId;
        if (!id) return;
        const { url } = await saveComicPage(id, dataUrl);
        set({ pageUrl: url });
      },
    }),
    {
      name: "webui-comic",
      storage: createJSONStorage(() => localStorage),
      // 不持久化執行期旗標
      partialize: (st) => ({
        title: st.title,
        premise: st.premise,
        systemPrompt: st.systemPrompt,
        systemBase: st.systemBase,
        panelCount: st.panelCount,
        think: st.think,
        style: st.style,
        negative: st.negative,
        characters: st.characters,
        settings: st.settings,
        layout: st.layout,
        panels: st.panels,
        view: st.view,
        projectId: st.projectId,
        pageUrl: st.pageUrl,
        versions: st.versions,
        savedAt: st.savedAt,
      }),
    }
  )
);

// 自動儲存：作品欄位任一變動就 debounce 後整份存到伺服器
let _saveTimer = null;
useComic.subscribe((st, prev) => {
  if (st._loading) return;
  if (!PROJECT_KEYS.some((k) => st[k] !== prev[k])) return;
  if (!st.projectId && projectIsEmpty(st)) return;
  clearTimeout(_saveTimer);
  _saveTimer = setTimeout(() => useComic.getState().saveProject(), AUTOSAVE_MS);
});
