// 圖片庫狀態：篩選條件（記在瀏覽器）、目前載入的圖、選取、詳細資訊、垃圾桶。
import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import {
  deleteImages,
  emptyTrash,
  fetchGallery,
  fetchGalleryNames,
  fetchImageInfo,
  fetchTrash,
  purgeImages,
  restoreImages,
} from "../lib/galleryApi";

const PAGE = 60;
let _seq = 0; // 篩選一改就作廢還在路上的舊請求

export const useGallery = create(
  persist(
    (set, get) => ({
      // 篩選（folder 空字串＝目前的圖片資料夾）
      folder: "",
      q: "",
      kind: "",
      usage: "",
      sort: "new",
      size: "m", // 格子大小 s / m / l
      // 資料
      items: [],
      total: 0,
      counts: {},
      folders: [],
      currentFolder: "",
      totalBytes: 0,
      trashCount: 0,
      loading: false,
      error: "",
      // 多選：selected = {檔名: {size, used}}（大小與用到幾處給選取列和刪除確認用）
      selecting: false,
      selected: {},
      lastPicked: null,
      selectingAll: false,
      // 剛刪掉的那一批（垃圾桶編號），選取列上可以「復原」
      undo: null,
      // 詳細資訊
      detail: null, // 目前打開的 name
      info: null,
      infoError: "",
      // 垃圾桶
      view: "grid", // grid | trash
      trash: { items: [], total: 0, total_bytes: 0 },

      setFilter(patch) {
        set({ ...patch, selected: {}, lastPicked: null });
        get().load();
      },
      setSize(size) {
        set({ size });
      },
      params(offset) {
        const { folder, q, kind, usage, sort } = get();
        return { folder, q: q.trim(), kind, usage, sort, offset, limit: PAGE };
      },
      async load() {
        const seq = ++_seq;
        set({ loading: true, error: "" });
        try {
          const d = await fetchGallery(get().params(0));
          if (seq !== _seq) return;
          // 記住的資料夾已經不在清單裡（設定改過）就回到目前的資料夾
          if (get().folder && !d.folders.some((f) => f.path === get().folder)) {
            set({ folder: "" });
            return get().load();
          }
          set({
            items: d.items,
            total: d.total,
            counts: d.counts,
            folders: d.folders,
            currentFolder: d.folder,
            totalBytes: d.total_bytes,
            trashCount: d.trash,
          });
        } catch (e) {
          if (seq === _seq) set({ error: e.message });
        } finally {
          if (seq === _seq) set({ loading: false });
        }
      },
      async loadMore() {
        const { items, total, loading } = get();
        if (loading || items.length >= total) return;
        const seq = _seq;
        set({ loading: true });
        try {
          const d = await fetchGallery(get().params(items.length));
          if (seq !== _seq) return;
          const have = new Set(get().items.map((i) => i.name));
          set({ items: [...get().items, ...d.items.filter((i) => !have.has(i.name))], total: d.total });
        } catch (e) {
          if (seq === _seq) set({ error: e.message });
        } finally {
          if (seq === _seq) set({ loading: false });
        }
      },

      // ---- 多選 ----
      setSelecting(on) {
        set({ selecting: on, selected: {}, lastPicked: null });
      },
      // 點任何一張的勾選框就進入多選；range＝從上一次點的那張選到這張（Shift）
      toggle(name, range = false) {
        const { items, selected, lastPicked } = get();
        const next = { ...selected };
        const pick = (it, on) => {
          if (on) next[it.name] = { size: it.size, used: it.used };
          else delete next[it.name];
        };
        const b = items.findIndex((i) => i.name === name);
        const a = range && lastPicked ? items.findIndex((i) => i.name === lastPicked) : -1;
        if (a >= 0 && b >= 0) {
          const on = !selected[name];
          for (const it of items.slice(Math.min(a, b), Math.max(a, b) + 1)) pick(it, on);
        } else if (b >= 0) {
          pick(items[b], !selected[name]);
        }
        set({ selected: next, lastPicked: name, selecting: true });
      },
      // 一整天（日期分段）全選 / 全不選
      selectGroup(groupItems, on) {
        const next = { ...get().selected };
        for (const it of groupItems) {
          if (on) next[it.name] = { size: it.size, used: it.used };
          else delete next[it.name];
        }
        set({ selected: next, selecting: true });
      },
      selectAllLoaded() {
        set({
          selected: Object.fromEntries(get().items.map((i) => [i.name, { size: i.size, used: i.used }])),
          selecting: true,
        });
      },
      // 符合目前篩選的每一張（還沒捲到、沒載入的也算）
      async selectAllMatching() {
        const { folder, q, kind, usage } = get();
        set({ selectingAll: true });
        try {
          const d = await fetchGalleryNames({ folder, q: q.trim(), kind, usage });
          set({
            selected: Object.fromEntries(d.items.map((i) => [i.name, { size: i.size, used: i.used }])),
            selecting: true,
          });
        } catch (e) {
          set({ error: e.message });
        } finally {
          set({ selectingAll: false });
        }
      },
      clearSelection() {
        set({ selected: {}, lastPicked: null });
      },

      // ---- 詳細資訊 ----
      async openDetail(name) {
        set({ detail: name, info: null, infoError: "" });
        try {
          const info = await fetchImageInfo(get().folder, name);
          if (get().detail === name) set({ info });
        } catch (e) {
          if (get().detail === name) set({ infoError: e.message });
        }
      },
      closeDetail() {
        set({ detail: null, info: null, infoError: "" });
      },
      // dir：-1 上一張 / 1 下一張；到已載入的最後一張時先載入下一頁
      async step(dir) {
        const { items, detail, total } = get();
        let i = items.findIndex((it) => it.name === detail);
        if (i < 0) return;
        if (dir > 0 && i === items.length - 1 && items.length < total) {
          await get().loadMore();
        }
        const list = get().items;
        const j = i + dir;
        if (j >= 0 && j < list.length) get().openDetail(list[j].name);
      },

      // ---- 刪除 / 垃圾桶 ----
      async remove(names) {
        const r = await deleteImages(get().folder, names);
        const gone = new Set(r.deleted);
        const { items, detail } = get();
        let nextDetail = null;
        if (detail && gone.has(detail)) {
          // 刪掉正在看的那張：跳到下一張（沒有就上一張）
          const i = items.findIndex((it) => it.name === detail);
          const rest = items.filter((it) => !gone.has(it.name));
          nextDetail = rest[Math.min(i, rest.length - 1)]?.name || null;
        }
        const selected = Object.fromEntries(Object.entries(get().selected).filter(([n]) => !gone.has(n)));
        set({
          items: items.filter((it) => !gone.has(it.name)),
          total: Math.max(0, get().total - gone.size),
          trashCount: get().trashCount + gone.size,
          selected,
          selecting: get().selecting && Object.keys(selected).length > 0,
          undo: r.trash_ids?.length ? { ids: r.trash_ids, n: r.trash_ids.length, at: Date.now() } : null,
        });
        if (detail && gone.has(detail)) {
          if (nextDetail) get().openDetail(nextDetail);
          else get().closeDetail();
        }
        get().load(); // 數量、已用 / 未用重新算
        return r;
      },
      // 把剛刪掉的那一批從垃圾桶放回去
      async undoDelete() {
        const u = get().undo;
        if (!u) return null;
        set({ undo: null });
        const r = await restoreImages(u.ids);
        await get().load();
        return r;
      },
      dismissUndo() {
        set({ undo: null });
      },
      setView(view) {
        set({ view, selecting: false, selected: {} });
        if (view === "trash") get().loadTrash();
        else get().load();
      },
      async loadTrash() {
        try {
          const trash = await fetchTrash();
          set({ trash, trashCount: trash.total, error: "" });
        } catch (e) {
          set({ error: e.message });
        }
      },
      async restore(ids) {
        const r = await restoreImages(ids);
        await get().loadTrash();
        return r;
      },
      async purge(ids) {
        await purgeImages(ids);
        await get().loadTrash();
      },
      async emptyTrash() {
        await emptyTrash();
        await get().loadTrash();
      },
    }),
    {
      name: "webui-gallery",
      storage: createJSONStorage(() => localStorage),
      partialize: (st) => ({ folder: st.folder, kind: st.kind, usage: st.usage, sort: st.sort, size: st.size }),
    }
  )
);
