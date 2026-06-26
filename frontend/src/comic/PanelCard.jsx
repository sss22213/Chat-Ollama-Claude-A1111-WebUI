import { useState } from "react";
import {
  Wand2,
  Loader2,
  RefreshCw,
  Trash2,
  X,
  Plus,
  MessageSquare,
  AlertCircle,
  FileText,
  Copy,
  Check,
} from "lucide-react";
import { useComic } from "../store/comic";
import { useChat } from "../store/chat";
import { useCT } from "./comicI18n";

const BUBBLE_TYPES = ["speech", "thought", "caption"];

// 小複製按鈕：複製文字並短暫顯示「已複製」
function CopyBtn({ text, ct }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      setTimeout(() => setDone(false), 1500);
    } catch {
      /* 忽略 */
    }
  };
  return (
    <button
      onClick={copy}
      className="flex items-center gap-1 text-[11px] text-gray-400 hover:text-emerald-300"
    >
      {done ? <Check size={12} /> : <Copy size={12} />}
      {done ? ct("copied") : ct("copy")}
    </button>
  );
}

const inputCls =
  "w-full rounded-md border border-ink-600 bg-ink-850 px-2 py-1 text-xs outline-none focus:border-ink-500";

export default function PanelCard({ panel, index }) {
  const ct = useCT();
  const characters = useComic((s) => s.characters);
  const style = useComic((s) => s.style); // 訂閱以便完整提示詞即時更新
  const negative = useComic((s) => s.negative);
  const composePrompt = useComic((s) => s.composePrompt);
  const setPanel = useComic((s) => s.setPanel);
  const removePanel = useComic((s) => s.removePanel);
  const toggleCharacterInPanel = useComic((s) => s.toggleCharacterInPanel);
  const generatePanel = useComic((s) => s.generatePanel);
  const addBubble = useComic((s) => s.addBubble);
  const updateBubble = useComic((s) => s.updateBubble);
  const removeBubble = useComic((s) => s.removeBubble);
  const health = useChat((s) => s.health);
  const [showFull, setShowFull] = useState(false);

  const gen = panel.status === "generating";
  const namedCast = characters.filter((c) => c.name.trim());
  // 實際會送給 A1111 的完整正向提示詞（畫風＋角色外觀/LoRA＋場景）
  // 依賴 style/characters/negative 訂閱，編輯時即時更新
  const fullPrompt = composePrompt(panel);

  return (
    <div className="flex flex-col overflow-hidden rounded-xl border border-ink-700 bg-ink-850">
      {/* 標頭 */}
      <div className="flex items-center gap-2 border-b border-ink-700 px-3 py-1.5">
        <span className="text-sm font-semibold text-gray-200">
          {ct("panel", { n: index + 1 })}
        </span>
        {panel.seed != null && (
          <span className="font-mono text-[10px] text-gray-600">
            seed {panel.seed}
          </span>
        )}
        <div className="flex-1" />
        <button
          onClick={() => setShowFull((v) => !v)}
          title={ct("viewFullPrompt")}
          className={`rounded-md p-1 transition ${
            showFull
              ? "bg-ink-700 text-gray-100"
              : "text-gray-500 hover:bg-ink-750 hover:text-gray-200"
          }`}
        >
          <FileText size={14} />
        </button>
        <button
          onClick={() => generatePanel(panel.id)}
          disabled={gen || !health.a1111}
          title={panel.image ? ct("regenerate") : ct("generatePanel")}
          className="flex items-center gap-1 rounded-md bg-emerald-600 px-2 py-1 text-xs text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-ink-700 disabled:text-gray-500"
        >
          {gen ? (
            <Loader2 size={13} className="animate-spin" />
          ) : panel.image ? (
            <RefreshCw size={13} />
          ) : (
            <Wand2 size={13} />
          )}
        </button>
        <button
          onClick={() => removePanel(panel.id)}
          title="✕"
          className="rounded-md p-1 text-gray-500 hover:bg-ink-750 hover:text-red-400"
        >
          <Trash2 size={14} />
        </button>
      </div>

      {/* 圖片 */}
      <div className="relative flex aspect-[4/5] items-center justify-center overflow-hidden bg-ink-900">
        {panel.image ? (
          <img
            src={panel.image.url}
            alt={`panel ${index + 1}`}
            className="h-full w-full object-cover"
          />
        ) : (
          <span className="text-xs text-gray-600">{ct("emptyPanelImg")}</span>
        )}
        {gen && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/50">
            <Loader2 size={26} className="animate-spin text-white" />
          </div>
        )}
        {panel.status === "error" && (
          <div className="absolute inset-x-0 bottom-0 flex items-center gap-1 bg-red-950/80 px-2 py-1 text-[11px] text-red-200">
            <AlertCircle size={12} /> {panel.error || ct("genFailed")}
          </div>
        )}
      </div>

      {/* 編輯 */}
      <div className="space-y-2 p-2.5">
        {/* 完整提示詞（送給 A1111）— 場景＋畫風＋角色外觀/LoRA */}
        {showFull && (
          <div className="space-y-1.5 rounded-lg border border-ink-700 bg-ink-900 p-2">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-medium text-gray-400">
                {ct("fullPrompt")}
              </span>
              <CopyBtn text={fullPrompt} ct={ct} />
            </div>
            <p className="max-h-32 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-gray-200">
              {fullPrompt || "—"}
            </p>
            {negative.trim() && (
              <>
                <div className="flex items-center justify-between border-t border-ink-700/60 pt-1.5">
                  <span className="text-[11px] font-medium text-gray-500">
                    {ct("negativePrompt")}
                  </span>
                  <CopyBtn text={negative} ct={ct} />
                </div>
                <p className="max-h-20 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-gray-500">
                  {negative}
                </p>
              </>
            )}
            <p className="text-[10px] text-gray-600">{ct("fullPromptHint")}</p>
          </div>
        )}

        {/* 場景提示詞 */}
        <textarea
          value={panel.prompt}
          onChange={(e) => setPanel(panel.id, { prompt: e.target.value })}
          placeholder={ct("promptPh")}
          rows={2}
          className={`${inputCls} resize-y font-mono`}
        />

        {/* 出場角色 */}
        {namedCast.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {namedCast.map((c) => {
              const on = panel.characters.includes(c.name);
              return (
                <button
                  key={c.id}
                  onClick={() => toggleCharacterInPanel(panel.id, c.name)}
                  className={`rounded-full border px-2 py-0.5 text-[11px] transition ${
                    on
                      ? "border-emerald-600/60 bg-emerald-600/20 text-emerald-300"
                      : "border-ink-600 text-gray-400 hover:bg-ink-800"
                  }`}
                >
                  {c.name}
                </button>
              );
            })}
          </div>
        )}

        {/* 對白 / 旁白氣泡 */}
        <div className="space-y-1.5">
          {panel.bubbles.map((b) => (
            <div key={b.id} className="flex items-start gap-1">
              <select
                value={b.type}
                onChange={(e) => updateBubble(panel.id, b.id, { type: e.target.value })}
                className="shrink-0 rounded-md border border-ink-600 bg-ink-850 px-1 py-1 text-[11px] outline-none focus:border-ink-500"
              >
                {BUBBLE_TYPES.map((tp) => (
                  <option key={tp} value={tp}>
                    {ct(
                      tp === "speech"
                        ? "bubbleSpeech"
                        : tp === "thought"
                        ? "bubbleThought"
                        : "bubbleCaption"
                    )}
                  </option>
                ))}
              </select>
              <div className="min-w-0 flex-1 space-y-1">
                {b.type !== "caption" && (
                  <input
                    value={b.speaker}
                    onChange={(e) =>
                      updateBubble(panel.id, b.id, { speaker: e.target.value })
                    }
                    placeholder={ct("speakerPh")}
                    className={inputCls}
                  />
                )}
                <textarea
                  value={b.text}
                  onChange={(e) =>
                    updateBubble(panel.id, b.id, { text: e.target.value })
                  }
                  placeholder={ct("linePh")}
                  rows={1}
                  className={`${inputCls} resize-y`}
                />
              </div>
              <button
                onClick={() => removeBubble(panel.id, b.id)}
                className="shrink-0 rounded-md p-1 text-gray-600 hover:bg-ink-750 hover:text-red-400"
              >
                <X size={13} />
              </button>
            </div>
          ))}
          <div className="flex gap-1.5">
            <button
              onClick={() => addBubble(panel.id, "speech")}
              className="flex items-center gap-1 rounded-md border border-ink-600 px-2 py-1 text-[11px] text-gray-400 hover:bg-ink-800"
            >
              <MessageSquare size={12} /> {ct("addLine")}
            </button>
            <button
              onClick={() => addBubble(panel.id, "caption")}
              className="flex items-center gap-1 rounded-md border border-ink-600 px-2 py-1 text-[11px] text-gray-400 hover:bg-ink-800"
            >
              <Plus size={12} /> {ct("captionLabel")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
