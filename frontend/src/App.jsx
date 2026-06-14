import { useEffect, useState } from "react";
import { useChat } from "./store/chat";
import Sidebar from "./components/Sidebar";
import ChatView from "./components/ChatView";
import TopBar from "./components/TopBar";
import SettingsModal from "./components/SettingsModal";

export default function App() {
  const loadResources = useChat((s) => s.loadResources);
  // 桌面預設展開側欄；行動裝置（< md）預設收起，改用覆蓋式抽屜
  const [sidebarOpen, setSidebarOpen] = useState(
    () => typeof window === "undefined" || window.innerWidth >= 768
  );
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    loadResources();
  }, [loadResources]);

  return (
    <div className="flex h-full w-full overflow-hidden bg-ink-900 text-[#ececec]">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="flex flex-1 flex-col min-w-0">
        <TopBar
          onToggleSidebar={() => setSidebarOpen((v) => !v)}
          onOpenSettings={() => setSettingsOpen(true)}
        />
        <ChatView />
      </div>
      {settingsOpen && <SettingsModal onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}
