import { useState } from "react";
import { UserPlus, X, Layers, Check, Loader2, ScanText, AlertCircle } from "lucide-react";
import { cardKeywords, isParsed, useComic } from "../store/comic";
import { useCT } from "./comicI18n";
import { getLoraWeight, setLoraWeight } from "./lora";
import LoraPicker from "../components/LoraPicker";

const fieldCls =
  "w-full rounded-md border border-ink-600 bg-ink-850 px-2 py-1 font-mono text-[11px] leading-relaxed outline-none focus:border-ink-500";

// 角色卡：角色關鍵字（範例 prompt）由 LLM 拆成人物特徵、預設服裝、範例場景；人物特徵與服裝＋LoRA
// 出圖時自動帶入維持跨格一致，服裝與場景分鏡時會依故事調整。解析結果可以直接改。
export default function CharacterCast() {
  const ct = useCT();
  const characters = useComic((s) => s.characters);
  const addCharacter = useComic((s) => s.addCharacter);
  const updateCharacter = useComic((s) => s.updateCharacter);
  const removeCharacter = useComic((s) => s.removeCharacter);
  const parseCharacters = useComic((s) => s.parseCharacters);
  const parsingCast = useComic((s) => s.parsingCast);
  const [loraFor, setLoraFor] = useState(null); // 正在挑 LoRA 的角色 id
  const [parseErr, setParseErr] = useState({}); // {角色 id: 錯誤}

  const parseOne = async (c) => {
    setParseErr((e) => ({ ...e, [c.id]: "" }));
    try {
      await parseCharacters({ ids: [c.id] });
    } catch (e) {
      setParseErr((x) => ({ ...x, [c.id]: e.message || "failed" }));
    }
  };

  return (
    <div className="space-y-2">
      {characters.map((c) => (
        <div
          key={c.id}
          className="space-y-1.5 rounded-lg border border-ink-700 bg-ink-800 p-2"
        >
          <div className="flex items-center gap-1.5">
            <input
              value={c.name}
              onChange={(e) => updateCharacter(c.id, { name: e.target.value })}
              placeholder={ct("charNamePh")}
              className="min-w-0 flex-1 rounded-md border border-ink-600 bg-ink-850 px-2 py-1 text-sm outline-none focus:border-ink-500"
            />
            <button
              onClick={() => removeCharacter(c.id)}
              title={ct("removeCharacter")}
              className="shrink-0 rounded-md p-1 text-gray-500 hover:bg-ink-750 hover:text-red-400"
            >
              <X size={15} />
            </button>
          </div>
          <textarea
            value={c.keywords ?? c.appearance ?? ""}
            onChange={(e) => updateCharacter(c.id, { keywords: e.target.value })}
            placeholder={ct("charKeywordsPh")}
            rows={3}
            data-testid="char-keywords"
            className="min-h-[4.5rem] w-full resize-y rounded-md border border-ink-600 bg-ink-850 px-2 py-1.5 font-mono text-xs leading-relaxed outline-none focus:border-ink-500"
          />
          {cardKeywords(c) && (
            <div className="flex items-center gap-1.5">
              <span
                data-testid="char-parse-state"
                className={`min-w-0 flex-1 truncate text-[10px] ${isParsed(c) ? "text-emerald-400" : "text-amber-300/90"}`}
              >
                {isParsed(c) ? ct("castParsed") : ct("castNotParsed")}
              </span>
              <button
                onClick={() => parseOne(c)}
                disabled={parsingCast || !c.name.trim()}
                title={c.name.trim() ? "" : ct("castNeedName")}
                data-testid="char-parse"
                className="flex shrink-0 items-center gap-1 rounded-md border border-ink-600 px-1.5 py-0.5 text-[11px] text-gray-300 hover:bg-ink-750 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {parsingCast ? <Loader2 size={12} className="animate-spin" /> : <ScanText size={12} />}
                {isParsed(c) ? ct("reparseCast") : ct("parseCast")}
              </button>
            </div>
          )}
          {parseErr[c.id] && (
            <div className="flex items-start gap-1 text-[11px] text-red-300">
              <AlertCircle size={12} className="mt-0.5 shrink-0" />
              <span className="break-words">{parseErr[c.id]}</span>
            </div>
          )}
          {/* 解析結果：人物特徵、服裝是每格的預設（分鏡可依故事在某格換掉）；姿勢、場景是分鏡時的參考 */}
          {isParsed(c) && (
            <div className="space-y-1 rounded-md border border-ink-700 bg-ink-850/60 p-1.5" data-testid="char-parsed">
              {[
                ["features", "featuresLabel"],
                ["outfit", "outfitLabel"],
                ["pose", "poseLabel"],
                ["scene", "sceneLabel"],
              ].map(([field, label]) => (
                <label key={field} className="block">
                  <span className="text-[10px] text-gray-500">{ct(label)}</span>
                  <textarea
                    value={c[field] || ""}
                    onChange={(e) => updateCharacter(c.id, { [field]: e.target.value })}
                    rows={1}
                    data-testid={`char-${field}`}
                    className={`${fieldCls} resize-y`}
                  />
                </label>
              ))}
            </div>
          )}
          <button
            onClick={() => setLoraFor(c.id)}
            className="flex items-center gap-1 rounded-md border border-ink-600 px-2 py-1 text-xs text-gray-300 hover:bg-ink-750"
          >
            <Layers size={13} /> {ct("pickLora")}
          </button>
          {c.lora ? (
            <div className="space-y-1 rounded-md border border-ink-700 bg-ink-850 p-1.5">
              <div className="flex items-center gap-1">
                <Check size={12} className="shrink-0 text-emerald-400" />
                <span
                  className="min-w-0 flex-1 truncate font-mono text-[11px] text-emerald-300"
                  title={c.lora}
                >
                  {c.lora}
                </span>
                <button
                  onClick={() => updateCharacter(c.id, { lora: "" })}
                  className="shrink-0 text-gray-500 hover:text-red-400"
                >
                  <X size={12} />
                </button>
              </div>
              <div className="flex items-center gap-2">
                <span className="shrink-0 text-[11px] text-gray-500">
                  {ct("loraWeight")}
                </span>
                <input
                  type="range"
                  min={0}
                  max={1.5}
                  step={0.05}
                  value={getLoraWeight(c.lora)}
                  onChange={(e) =>
                    updateCharacter(c.id, {
                      lora: setLoraWeight(c.lora, Number(e.target.value)),
                    })
                  }
                  className="min-w-0 flex-1 accent-emerald-500"
                />
                <input
                  type="number"
                  min={0}
                  max={2}
                  step={0.05}
                  value={getLoraWeight(c.lora)}
                  onChange={(e) =>
                    updateCharacter(c.id, {
                      lora: setLoraWeight(c.lora, Number(e.target.value)),
                    })
                  }
                  className="w-14 shrink-0 rounded-md border border-ink-600 bg-ink-850 px-1 py-0.5 text-[11px] outline-none focus:border-ink-500"
                />
              </div>
            </div>
          ) : null}
        </div>
      ))}

      <button
        onClick={addCharacter}
        className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-ink-600 py-1.5 text-xs text-gray-400 hover:bg-ink-800"
      >
        <UserPlus size={14} /> {ct("addCharacter")}
      </button>

      {loraFor && (
        <LoraPicker
          streaming={false}
          onInsert={(lo) => {
            const tag =
              (lo.prompt && lo.prompt.trim()) || `<lora:${lo.name}:1>`;
            updateCharacter(loraFor, { lora: tag });
            setLoraFor(null);
          }}
          onGenerate={(lo) => {
            const tag =
              (lo.prompt && lo.prompt.trim()) || `<lora:${lo.name}:1>`;
            updateCharacter(loraFor, { lora: tag });
            setLoraFor(null);
          }}
          onClose={() => setLoraFor(null)}
        />
      )}
    </div>
  );
}
