import { useEffect, useState } from "react";
import { useChat } from "./store/chat";
import Sidebar from "./components/Sidebar";
import ChatView from "./components/ChatView";
import TopBar from "./components/TopBar";
import SettingsModal from "./components/SettingsModal";

export default function App() {
  const loadResources = useChat((s) => s.loadResources);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    loadResources();
  }, [loadResources]);

  return (
    <div className="flex h-full w-full overflow-hidden bg-ink-900 text-[#ececec]">
      <Sidebar open={sidebarOpen} onToggle={() => setSidebarOpen((v) => !v)} />
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
