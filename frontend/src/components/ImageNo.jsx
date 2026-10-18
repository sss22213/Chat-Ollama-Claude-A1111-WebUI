import { useT } from "../i18n";

// 圖左下角的編號：對話中的第幾張圖（跟後端 chat.conversation_images 同一套），
// 可以跟 AI 說「把 #3 加到 LoRA 的範例圖」。父元素要是 relative。
export default function ImageNo({ n }) {
  const t = useT();
  if (!n) return null;
  return (
    <span
      data-testid="image-no"
      title={t("imageNoHint", { n })}
      className="absolute bottom-1.5 left-1.5 rounded-md bg-black/65 px-1.5 py-0.5 font-mono text-[11px] text-gray-100"
    >
      #{n}
    </span>
  );
}
