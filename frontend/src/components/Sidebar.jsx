import { Plus, MessageSquare, Trash2, PanelLeftClose } from "lucide-react";
import { useChat } from "../store/chat";
import { useT } from "../i18n";

export default function Sidebar({ open, onToggle }) {
  const t = useT();
  const conversations = useChat((s) => s.conversations);
  const currentId = useChat((s) => s.currentId);
  const createConversation = useChat((s) => s.createConversation);
  const selectConversation = useChat((s) => s.selectConversation);
  const deleteConversation = useChat((s) => s.deleteConversation);

  if (!open) return null;

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-ink-700 bg-ink-850">
      <div className="flex items-center gap-2 p-3">
        <button
          onClick={createConversation}
          className="flex flex-1 items-center gap-2 rounded-lg border border-ink-600 px-3 py-2 text-sm hover:bg-ink-750"
        >
          <Plus size={16} /> {t("newChat")}
        </button>
        <button
          onClick={onToggle}
          title={t("sidebar")}
          className="rounded-lg p-2 text-gray-400 hover:bg-ink-750"
        >
          <PanelLeftClose size={18} />
        </button>
      </div>

      <div className="flex-1 space-y-1 overflow-y-auto px-2 pb-2">
        {conversations.map((c) => (
          <div
            key={c.id}
            onClick={() => selectConversation(c.id)}
            className={`group flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm ${
              c.id === currentId ? "bg-ink-700" : "hover:bg-ink-750"
            }`}
          >
            <MessageSquare size={15} className="shrink-0 text-gray-400" />
            <span className="flex-1 truncate">{c.title || t("newChat")}</span>
            <button
              onClick={(e) => {
                e.stopPropagation();
                deleteConversation(c.id);
              }}
              className="shrink-0 text-gray-500 opacity-0 hover:text-red-400 group-hover:opacity-100"
              title={t("deleteChat")}
            >
              <Trash2 size={15} />
            </button>
          </div>
        ))}
      </div>

      <div className="border-t border-ink-700 p-3 text-xs text-gray-500">
        Chat · Ollama · A1111
      </div>
    </aside>
  );
}
