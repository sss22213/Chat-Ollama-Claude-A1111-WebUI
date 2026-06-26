import { useEffect, useState } from "react";
import { useChat } from "./store/chat";
import App from "./App";
import ComicStudio from "./comic/ComicStudio";

// 極簡 hash 路由：#/comic → 漫畫工作室，其餘 → 聊天。
// 不引入 react-router，沿用既有單頁部署（nginx SPA fallback / vite）。
function routeFromHash() {
  return (window.location.hash || "").replace(/^#\/?/, "").split(/[/?]/)[0];
}

export function navigate(route) {
  window.location.hash = route ? `/${route}` : "/";
}

export default function Root() {
  const loadResources = useChat((s) => s.loadResources);
  const [route, setRoute] = useState(routeFromHash);

  // 資源（模型/引擎/SD 模型/取樣器/設定/對話）只載一次，兩個頁面共用同一個 store。
  useEffect(() => {
    loadResources();
  }, [loadResources]);

  useEffect(() => {
    const onHash = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  return route === "comic" ? <ComicStudio /> : <App />;
}
