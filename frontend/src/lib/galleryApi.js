// 圖片庫 API：瀏覽、縮圖、詳細資訊（PNG 文字區塊 / EXIF）、刪除到垃圾桶、還原、永久刪除。

const enc = encodeURIComponent;

async function req(method, url, body) {
  const r = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
  return data;
}

const qs = (params) =>
  Object.entries(params)
    .filter(([, v]) => v !== "" && v != null)
    .map(([k, v]) => `${k}=${enc(v)}`)
    .join("&");

// {folder, q, kind, usage, sort, offset, limit} → {items, total, counts, folders, trash, total_bytes}
export const fetchGallery = (params) => req("GET", `/api/gallery?${qs(params)}`);
// 符合篩選的所有圖（多選「全選符合條件」用）→ {items: [{name, size, used}], total}
export const fetchGalleryNames = (params) => req("GET", `/api/gallery/names?${qs(params)}`);
export const fetchImageInfo = (folder, name) => req("GET", `/api/gallery/info?${qs({ folder, name })}`);
export const deleteImages = (folder, names) => req("POST", "/api/gallery/delete", { folder, names });
export const fetchTrash = () => req("GET", "/api/gallery/trash");
export const restoreImages = (ids) => req("POST", "/api/gallery/trash/restore", { ids });
export const purgeImages = (ids) => req("POST", "/api/gallery/trash/purge", { ids });
export const emptyTrash = () => req("POST", "/api/gallery/trash/purge", { all: true });

// 縮圖網址帶 mtime：圖換了網址就變，瀏覽器快取不會拿到舊的
export const thumbUrl = (folder, item, size = 384) =>
  `/api/gallery/thumb?${qs({ folder, name: item.name, size, v: Math.floor(item.mtime || 0) })}`;
export const trashThumbUrl = (id, size = 384) => `/api/gallery/trash/thumb?${qs({ id, size })}`;

export function formatBytes(n) {
  if (!n) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  return `${(n / 1024 ** i).toFixed(i >= 2 ? 1 : 0)} ${units[i]}`;
}
