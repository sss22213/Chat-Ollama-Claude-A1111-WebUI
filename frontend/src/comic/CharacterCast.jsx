import { useState } from "react";
import { UserPlus, X, Layers, Check } from "lucide-react";
import { useComic } from "../store/comic";
import { useCT } from "./comicI18n";
import { getLoraWeight, setLoraWeight } from "./lora";
import LoraPicker from "../components/LoraPicker";

// 角色卡：固定外觀 tag ＋ LoRA，出圖時自動帶入維持跨格一致。
export default function CharacterCast() {
  const ct = useCT();
  const characters = useComic((s) => s.characters);
  const addCharacter = useComic((s) => s.addCharacter);
  const updateCharacter = useComic((s) => s.updateCharacter);
  const removeCharacter = useComic((s) => s.removeCharacter);
  const [loraFor, setLoraFor] = useState(null); // 正在挑 LoRA 的角色 id

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
            value={c.appearance}
            onChange={(e) => updateCharacter(c.id, { appearance: e.target.value })}
            placeholder={ct("charAppearancePh")}
            rows={3}
            className="min-h-[4.5rem] w-full resize-y rounded-md border border-ink-600 bg-ink-850 px-2 py-1.5 text-xs leading-relaxed outline-none focus:border-ink-500"
          />
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
