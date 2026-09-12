// 圖片說故事：上傳圖片 → LLM 看圖生成故事或漫畫腳本（與漫畫工作室分開的頁面）。
// 圖片只放記憶體（不持久化，避免 localStorage 爆量）；結果與選項會保留。
import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import { generateFromImage } from "../lib/storyApi";
import { stripPrefix } from "../lib/image";

const uid = () =>
  (crypto.randomUUID && crypto.randomUUID()) ||
  Math.random().toString(36).slice(2);

// 張數不設上限。context 夠不夠用 estimateTokens 粗估給使用者看，超過請自行調 num_ctx 或減圖。
// 圖片送出前縮到長邊 1536px，qwen-VL / Claude 這種尺寸一張約 2k token。
export const TOKENS_PER_IMAGE = 2000;
const PROMPT_TOKENS = 1500; // system + 表情白名單 + 使用者指示
const OUTPUT_TOKENS = { short: 800, medium: 2000, long: 4000 };

export function estimateTokens({ count, mode, length, panelCount }) {
  if (mode === "panels") {
    // 分鏡模式是兩段式：先一張一張描述（一次只送一張圖），再把編號描述交給模型純文字寫作。
    // 所以要看的是「單次呼叫的峰值」而不是全部圖片加總：描述一張 ≈ 一張圖 + 300；
    // 寫作 ≈ 提示 + 每格描述約 200 + 每格輸出約 300。
    const describe = TOKENS_PER_IMAGE + PROMPT_TOKENS + 300;
    const write = PROMPT_TOKENS + count * 200 + 500 + count * 300;
    return Math.max(describe, write);
  }
  const out =
    mode === "comic"
      ? 800 + (Number(panelCount) || 6) * 250
      : OUTPUT_TOKENS[length] || 2000;
  return count * TOKENS_PER_IMAGE + PROMPT_TOKENS + out;
}

export const useStory = create(
  persist(
    (set, get) => ({
      mode: "story", // story | comic | panels（上傳圖片即分鏡，AI 補每格文字）
      length: "medium", // story：short | medium | long
      panelCount: 6, // comic
      instructions: "",
      think: false, // Ollama 思考型模型是否先思考
      result: null, // {mode:"story", title, story} | {mode:"comic", title, premise, style, characters, panels}
      error: "",

      // ---- 執行期（不持久化）----
      images: [], // [{id, dataUrl}]
      busy: false,
      notices: [], // 上次生成時後端的提醒（例如自動改用不思考）

      set(patch) {
        set(patch);
      },
      addImages(dataUrls) {
        set((st) => ({
          images: [...st.images, ...dataUrls.map((d) => ({ id: uid(), dataUrl: d }))],
        }));
      },
      removeImage(id) {
        set((st) => ({ images: st.images.filter((i) => i.id !== id) }));
      },
      // 調整順序（分鏡模式的閱讀順序 = 圖片順序）
      moveImage(id, dir) {
        set((st) => {
          const i = st.images.findIndex((x) => x.id === id);
          const j = i + dir;
          if (i < 0 || j < 0 || j >= st.images.length) return {};
          const images = [...st.images];
          [images[i], images[j]] = [images[j], images[i]];
          return { images };
        });
      },
      clearImages() {
        set({ images: [] });
      },

      async generate({ engine, model, lang, numCtx }) {
        const { images, mode, length, panelCount, instructions, think, busy } = get();
        if (!images.length || busy) return;
        set({ busy: true, error: "", result: null, notices: [] });
        try {
          const data = await generateFromImage({
            engine,
            model,
            images: images.map((i) => stripPrefix(i.dataUrl)),
            mode,
            lang,
            instructions,
            length,
            panel_count: panelCount,
            num_ctx: numCtx,
            think: engine === "ollama" ? think : undefined,
          });
          set({ result: data, notices: Array.isArray(data.notices) ? data.notices : [] });
        } catch (e) {
          set({ error: e.message || "failed" });
        } finally {
          set({ busy: false });
        }
      },

      reset() {
        set({ result: null, error: "", images: [], instructions: "" });
      },
    }),
    {
      name: "webui-story",
      storage: createJSONStorage(() => localStorage),
      partialize: (st) => ({
        mode: st.mode,
        length: st.length,
        panelCount: st.panelCount,
        instructions: st.instructions,
        think: st.think,
        result: st.result,
      }),
    }
  )
);
