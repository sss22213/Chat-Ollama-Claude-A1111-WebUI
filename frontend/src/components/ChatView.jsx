import { useEffect, useRef } from "react";
import { useChat } from "../store/chat";
import { useT } from "../i18n";
import Message from "./Message";
import Composer from "./Composer";
import { Wand2, Loader2 } from "lucide-react";

export default function ChatView() {
  const convo = useChat((s) => s.currentConversation());
  const scrollRef = useRef(null);
  // messages 為 undefined 代表正從後端載入中
  const loading = convo && convo.messages === undefined;
  const messages = convo?.messages || [];

  // 串流時自動捲到底
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  return (
    <div className="flex flex-1 flex-col min-h-0">
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl px-4 py-6">
          {loading ? (
            <LoadingState />
          ) : messages.length === 0 ? (
            <EmptyState />
          ) : (
            messages.map((m) => <Message key={m.id} msg={m} />)
          )}
        </div>
      </div>
      <Composer />
    </div>
  );
}

function LoadingState() {
  const t = useT();
  return (
    <div className="flex items-center justify-center gap-2 py-24 text-sm text-gray-500">
      <Loader2 size={16} className="animate-spin" /> {t("loading")}
    </div>
  );
}

function EmptyState() {
  const t = useT();
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-24 text-center text-gray-400">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-ink-800">
        <Wand2 size={26} className="text-emerald-400" />
      </div>
      <h1 className="text-xl font-semibold text-gray-200">{t("emptyTitle")}</h1>
      <p className="max-w-md text-sm leading-relaxed">
        {t("emptyDesc")}
        <br />
        {t("emptyHint")}
      </p>
    </div>
  );
}
