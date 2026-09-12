// 圖片讀取工具：聊天附件與「圖片說故事」共用。

// 原圖位元組（不重壓，保留 PNG metadata 給 PNG Info 用）。
export const fileToDataUrl = (file) =>
  new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = reject;
    r.readAsDataURL(file);
  });

// 讀取圖片並「縮圖＋重壓」後再用，避免大圖（數 MB base64）塞爆記憶體/localStorage。
// 對 vision 與 img2img 來說，長邊 1536px、JPEG 0.85 已綽綽有餘。
export const readAsDataUrl = (file, maxDim = 1536, quality = 0.85) =>
  new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      const scale = Math.min(1, maxDim / Math.max(img.width, img.height));
      const w = Math.max(1, Math.round(img.width * scale));
      const h = Math.max(1, Math.round(img.height * scale));
      const canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      canvas.getContext("2d").drawImage(img, 0, 0, w, h);
      try {
        resolve(canvas.toDataURL("image/jpeg", quality));
      } catch (e) {
        reject(e);
      }
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("讀取圖片失敗"));
    };
    img.src = url;
  });

// data URL → 純 base64
export const stripPrefix = (dataUrl) => (dataUrl || "").replace(/^data:[^,]*,/, "");

// 從 FileList / DataTransfer / 剪貼簿取出圖片檔
export const imageFilesFrom = (list) =>
  Array.from(list || []).filter((f) => f && f.type && f.type.startsWith("image/"));
