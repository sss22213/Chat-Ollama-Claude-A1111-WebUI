/**
 * 複製文字到剪貼簿，成功回 true。
 * navigator.clipboard 只在安全環境（HTTPS / localhost）才有；用區網 IP（http://192.168.x.x:5273）
 * 開網頁時沒有它，改用隱藏 textarea + document.execCommand("copy")（仍需在點擊事件中呼叫）。
 */
export async function copyText(text) {
  const s = String(text ?? "");
  if (window.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(s);
      return true;
    } catch {
      /* 權限被拒等：改用舊方法 */
    }
  }
  return legacyCopy(s);
}

function legacyCopy(text) {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", ""); // 手機上不跳出鍵盤
  ta.style.cssText = "position:fixed;top:0;left:0;width:1px;height:1px;padding:0;border:0;opacity:0;";
  const prev = document.activeElement;
  document.body.appendChild(ta);
  ta.select();
  ta.setSelectionRange(0, text.length); // iOS Safari 需要
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  ta.remove();
  prev?.focus?.({ preventScroll: true });
  return ok;
}
