import { useGallery } from "../store/gallery";
import { useGT } from "./galleryI18n";

// 刪除前確認：有被用到的圖多一句提醒
export function useConfirmDelete() {
  const gt = useGT();
  const remove = useGallery((s) => s.remove);
  return async (names, usedCount) => {
    if (!names.length) return null;
    const msg = [
      gt("confirmDelete", { n: names.length }),
      usedCount ? gt("confirmDeleteUsed", { n: usedCount }) : "",
      gt("confirmDeleteRestore"),
    ]
      .filter(Boolean)
      .join("\n\n");
    if (!window.confirm(msg)) return null;
    return remove(names);
  };
}
