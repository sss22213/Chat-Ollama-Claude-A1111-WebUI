import { useState } from "react";
import Sidebar from "./components/Sidebar";
import ChatView from "./components/ChatView";
import TopBar from "./components/TopBar";
import SettingsModal from "./components/SettingsModal";
import HistoryModal from "./components/HistoryModal";
import LoraBrowser from "./components/LoraBrowser";
import SkillPicker from "./components/SkillPicker";
import { navigate } from "./Root";

export default function App() {
  // 桌面預設展開側欄；行動裝置（< md）預設收起，改用覆蓋式抽屜
  const [sidebarOpen, setSidebarOpen] = useState(
    () => typeof window === "undefined" || window.innerWidth >= 768
  );
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [loraBrowserOpen, setLoraBrowserOpen] = useState(false);
  const [skillsOpen, setSkillsOpen] = useState(false);

  return (
    <div className="flex h-full w-full overflow-hidden bg-ink-900 text-[#ececec]">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="flex flex-1 flex-col min-w-0">
        <TopBar
          onToggleSidebar={() => setSidebarOpen((v) => !v)}
          onOpenSettings={() => setSettingsOpen(true)}
          onOpenHistory={() => setHistoryOpen(true)}
          onOpenLoras={() => setLoraBrowserOpen(true)}
          onOpenComic={() => navigate("comic")}
          onOpenSkills={() => setSkillsOpen(true)}
        />
        <ChatView />
      </div>
      {settingsOpen && <SettingsModal onClose={() => setSettingsOpen(false)} />}
      {historyOpen && <HistoryModal onClose={() => setHistoryOpen(false)} />}
      {loraBrowserOpen && (
        <LoraBrowser onClose={() => setLoraBrowserOpen(false)} />
      )}
      {skillsOpen && <SkillPicker onClose={() => setSkillsOpen(false)} />}
    </div>
  );
}
