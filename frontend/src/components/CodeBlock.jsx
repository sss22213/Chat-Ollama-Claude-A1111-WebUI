import { useRef, useState } from "react";
import { Check, Code2, Copy } from "lucide-react";
import { useT } from "../i18n";
import { copyText } from "../lib/clipboard";

// ```python 的語言名：Markdown 放在 <code> 的 class（language-python）
function languageOf(node) {
  const code = node?.children?.find((c) => c.tagName === "code");
  const cls = [].concat(code?.properties?.className || []).find((c) => String(c).startsWith("language-"));
  return cls ? String(cls).slice("language-".length) : "";
}

/** Markdown 的程式碼框：上方標題列放語言名與複製鈕，不會蓋到程式碼。 */
function CodeBlock({ node, ...props }) {
  const t = useT();
  const pre = useRef(null);
  const timer = useRef(0);
  const [copied, setCopied] = useState(false);
  const lang = languageOf(node);
  const label = t(copied ? "copied" : "copy");
  const copy = async () => {
    // 從畫面取文字：語法上色後 children 是一堆 span。Markdown 程式碼結尾固定多一個換行，不複製
    if (!(await copyText(pre.current.textContent.replace(/\n$/, "")))) return;
    setCopied(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="code-block" data-testid="code-block">
      <div className="code-block-bar">
        <span className="flex min-w-0 items-center gap-1.5 text-gray-400">
          {lang && <Code2 size={14} className="shrink-0" />}
          <span className="truncate" data-testid="code-lang">
            {lang}
          </span>
        </span>
        <button
          type="button"
          onClick={copy}
          title={label}
          aria-label={label}
          data-testid="code-copy"
          className={`flex shrink-0 items-center gap-1 rounded-md px-2 py-1.5 hover:bg-ink-700 sm:py-1 ${
            copied ? "text-emerald-300" : "text-gray-400 hover:text-gray-200"
          }`}
        >
          {copied ? <Check size={14} /> : <Copy size={14} />}
          {label}
        </button>
      </div>
      <pre ref={pre} {...props} />
    </div>
  );
}

// 給 <Markdown components={…}>。固定同一個物件：串流時每次重畫才不會換掉元件、清掉「已複製」狀態
export const markdownComponents = { pre: CodeBlock };
