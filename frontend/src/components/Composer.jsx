import { useEffect, useRef, useState } from "react";
import { ArrowUp, Square, ImagePlus, X, FileText, Users, Layers } from "lucide-react";
import { useChat } from "../store/chat";
import { useT } from "../i18n";
import PngInfoModal from "./PngInfoModal";
import CharacterPicker from "./CharacterPicker";
import LoraPicker from "./LoraPicker";

// 原圖位元組（不重壓，保留 PNG metadata 給 PNG Info 用）。過大則不保留以省記憶體。
const MAX_ORIGINAL = 12 * 1024 * 1024; // 12MB
const fileToDataUrl = (file) =>
  new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = reject;
    r.readAsDataURL(file);
  });

// 讀取圖片並「縮圖＋重壓」後再用，避免大圖（數 MB base64）塞爆記憶體/localStorage。
// 對 vision 與 img2img 來說，長邊 1536px、JPEG 0.85 已綽綽有餘。
const readAsDataUrl = (file, maxDim = 1536, quality = 0.85) =>
  new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      const scale = Math.min(1, maxDim / Math.max(img.width, img.height));
      const w = Math.max(1, Math.round(img.width * scale));
      const h = Math.max(1, Math.round(img.height * scale));
      const canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      canvas.getContext("2d").drawImage(img, 0, 0, w, h);
      try {
        resolve(canvas.toDataURL("image/jpeg", quality));
      } catch (e) {
        reject(e);
      }
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("讀取圖片失敗"));
    };
    img.src = url;
  });

export default function Composer() {
  const t = useT();
  const [text, setText] = useState("");
  const streaming = useChat((s) => s.streaming);
  const sendMessage = useChat((s) => s.sendMessage);
  const stopStreaming = useChat((s) => s.stopStreaming);
  const attachments = useChat((s) => s.attachments);
  const addAttachment = useChat((s) => s.addAttachment);
  const removeAttachment = useChat((s) => s.removeAttachment);
  const composerDraft = useChat((s) => s.composerDraft);
  const setComposerDraft = useChat((s) => s.setComposerDraft);
  const composerInsert = useChat((s) => s.composerInsert);
  const insertComposer = useChat((s) => s.insertComposer);
  const generateCharacter = useChat((s) => s.generateCharacter);
  const generateLora = useChat((s) => s.generateLora);
  const taRef = useRef(null);
  const fileRef = useRef(null);
  const [pngFor, setPngFor] = useState(null); // 正在看 PNG Info 的附件原圖
  const [charOpen, setCharOpen] = useState(false); // 角色搜尋器
  const [loraOpen, setLoraOpen] = useState(false); // LoRA 搜尋器

  // 調整輸入框高度（內容變動後）
  const resizeTextarea = () => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  };

  // 把角色接到目前輸入內容後面（自動補逗號）；有完整提示詞就帶入完整的
  const insertTag = (c) => {
    const piece = (typeof c === "object" ? c?.prompt?.trim() || c?.tag : c) || "";
    setText((prev) => {
      const base = prev.trim().replace(/[,，\s]*$/, "");
      return base ? `${base}, ${piece}` : piece;
    });
    requestAnimationFrame(() => {
      taRef.current?.focus();
      resizeTextarea();
    });
  };

  // 外部（如「套用歷史」）要帶入輸入框的草稿：填入後清回 null，並聚焦／調整高度
  useEffect(() => {
    if (composerDraft == null) return;
    setText(composerDraft);
    setComposerDraft(null);
    requestAnimationFrame(() => {
      const el = taRef.current;
      if (!el) return;
      el.focus();
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 200) + "px";
      el.setSelectionRange(el.value.length, el.value.length);
    });
  }, [composerDraft, setComposerDraft]);

  // 外部（如 LoRA 瀏覽器）要「附加」的片段：沿用 insertTag 的接逗號邏輯，取用後清回 null
  useEffect(() => {
    if (composerInsert == null) return;
    insertTag(composerInsert);
    insertComposer(null);
  }, [composerInsert, insertComposer]);

  const submit = () => {
    if ((!text.trim() && attachments.length === 0) || streaming) return;
    // 純附件無文字時給個預設提示
    sendMessage(text.trim() || t("seeThisImage"));
    setText("");
    if (taRef.current) taRef.current.style.height = "auto";
  };

  const onKeyDown = (e) => {
    // Shift+Enter 送出；Enter 換行
    if (e.key === "Enter" && e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const onInput = (e) => {
    setText(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  };

  // 縮圖（持久化/vision）+ 原圖（PNG Info）一起加進附件
  const attachFile = async (f) => {
    const downscaled = await readAsDataUrl(f);
    const original = f.size <= MAX_ORIGINAL ? await fileToDataUrl(f) : null;
    addAttachment(downscaled, original);
  };

  const onPickFiles = async (e) => {
    const files = [...(e.target.files || [])].filter((f) =>
      f.type.startsWith("image/")
    );
    for (const f of files) await attachFile(f);
    e.target.value = "";
  };

  const onPaste = async (e) => {
    const imgs = [...e.clipboardData.items].filter((i) =>
      i.type.startsWith("image/")
    );
    if (imgs.length) {
      e.preventDefault();
      for (const i of imgs) await attachFile(i.getAsFile());
    }
  };

  return (
    <div className="px-4 pb-4">
      <div className="mx-auto w-full max-w-3xl">
        {/* 附件縮圖 */}
        {attachments.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {attachments.map((a) => (
              <div
                key={a.id}
                className="group relative h-16 w-16 overflow-hidden rounded-lg border border-ink-600"
              >
                <img
                  src={a.dataUrl}
                  alt="attachment"
                  className="h-full w-full object-cover"
                />
                <button
                  onClick={() => removeAttachment(a.id)}
                  className="absolute right-0.5 top-0.5 rounded-full bg-black/70 p-0.5 text-white opacity-0 group-hover:opacity-100"
                  title={t("removeAttachment")}
                >
                  <X size={12} />
                </button>
                <button
                  onClick={() => setPngFor(a.original || a.dataUrl)}
                  className="absolute bottom-0.5 right-0.5 rounded-full bg-black/70 p-0.5 text-white opacity-0 group-hover:opacity-100"
                  title={t("pngInfo")}
                >
                  <FileText size={12} />
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="flex items-end gap-2 rounded-2xl border border-ink-600 bg-ink-800 px-2 py-2 focus-within:border-ink-500">
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            multiple
            hidden
            onChange={onPickFiles}
          />
          <button
            onClick={() => fileRef.current?.click()}
            title={t("attachHint")}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-gray-400 hover:bg-ink-700 hover:text-gray-200"
          >
            <ImagePlus size={18} />
          </button>
          <button
            onClick={() => setCharOpen(true)}
            title={t("characters")}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-gray-400 hover:bg-ink-700 hover:text-gray-200"
          >
            <Users size={18} />
          </button>
          <button
            onClick={() => setLoraOpen(true)}
            title={t("loras")}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-gray-400 hover:bg-ink-700 hover:text-gray-200"
          >
            <Layers size={18} />
          </button>
          <textarea
            ref={taRef}
            value={text}
            onChange={onInput}
            onKeyDown={onKeyDown}
            onPaste={onPaste}
            rows={1}
            placeholder={t("composerPlaceholder")}
            className="max-h-[200px] flex-1 resize-none bg-transparent py-1.5 text-[0.95rem] outline-none placeholder:text-gray-500"
          />
          {streaming ? (
            <button
              onClick={stopStreaming}
              title={t("stop")}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-red-600 text-white hover:bg-red-500"
            >
              <Square size={16} fill="currentColor" />
            </button>
          ) : (
            <button
              onClick={submit}
              disabled={!text.trim() && attachments.length === 0}
              title={t("send")}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-emerald-600 text-white enabled:hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-ink-600 disabled:text-gray-500"
            >
              <ArrowUp size={18} />
            </button>
          )}
        </div>
        <p className="mt-1.5 px-1 text-center text-xs text-gray-600">
          {t("composerFooter")}
        </p>
      </div>

      {pngFor && (
        <PngInfoModal image={pngFor} onClose={() => setPngFor(null)} />
      )}

      {charOpen && (
        <CharacterPicker
          streaming={streaming}
          onInsert={insertTag}
          onGenerate={(c) => {
            generateCharacter(c);
            setCharOpen(false);
          }}
          onClose={() => setCharOpen(false)}
        />
      )}

      {loraOpen && (
        <LoraPicker
          streaming={streaming}
          onInsert={insertTag}
          onGenerate={(c) => {
            generateLora(c);
            setLoraOpen(false);
          }}
          onClose={() => setLoraOpen(false)}
        />
      )}
    </div>
  );
}
