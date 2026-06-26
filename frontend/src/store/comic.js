// 漫畫工作室狀態：劇本、角色卡、分鏡格、出圖設定、對白氣泡。
// 出圖重用 lib/api.js 的 generateImage（txt2img）；分鏡用 lib/comicApi.js。
import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import { generateImage } from "../lib/api";
import { generateStoryboard } from "../lib/comicApi";

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
      type: "speech",
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

      // ---- 執行期（不持久化）----
      storyboarding: false,
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
        set((st) => ({
          characters: st.characters.map((c) =>
            c.id === id ? { ...c, ...patch } : c
          ),
        }));
      },
      removeCharacter(id) {
        const removed = get().characters.find((c) => c.id === id);
        set((st) => ({ characters: st.characters.filter((c) => c.id !== id) }));
        // 同步把分鏡格裡引用到的名字移除
        if (removed?.name) {
          set((st) => ({
            panels: st.panels.map((p) => ({
              ...p,
              characters: p.characters.filter((n) => n !== removed.name),
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
          characters: p.characters.includes(name)
            ? p.characters.filter((n) => n !== name)
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
      composePrompt(panel) {
        const { characters, style } = get();
        const present = (panel.characters || [])
          .map((n) => characters.find((c) => c.name === n))
          .filter(Boolean);
        const charParts = present.flatMap((c) =>
          [c.appearance, c.lora].map((s) => (s || "").trim()).filter(Boolean)
        );
        const parts = [style, ...charParts, panel.prompt]
          .map((s) => (s || "").trim())
          .filter(Boolean);
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
        const { premise, panelCount, characters, style, systemPrompt, systemBase } =
          get();
        if (!premise.trim() || get().storyboarding) return;
        set({ storyboarding: true });
        try {
          const data = await generateStoryboard({
            engine,
            model,
            premise,
            panel_count: panelCount,
            characters: characters
              .filter((c) => c.name.trim())
              .map((c) => ({ name: c.name.trim(), appearance: c.appearance })),
            style,
            lang,
            num_ctx: numCtx,
            system: systemPrompt,
            system_base: systemBase,
          });
          const panels = (data.panels || []).map((p) =>
            newPanel({
              prompt: p.prompt || "",
              characters: Array.isArray(p.characters) ? p.characters : [],
              bubbles: bubblesFromScript(p.dialogue, p.caption),
            })
          );
          set({ panels });
        } finally {
          set({ storyboarding: false });
        }
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
          view: "grid",
        });
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
        style: st.style,
        negative: st.negative,
        characters: st.characters,
        settings: st.settings,
        layout: st.layout,
        panels: st.panels,
        view: st.view,
      }),
    }
  )
);
