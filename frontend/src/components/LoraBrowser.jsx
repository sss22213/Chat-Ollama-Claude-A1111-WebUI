import { useCallback, useEffect, useRef, useState } from "react";
import {
  X,
  Search,
  Layers,
  Loader2,
  ArrowLeft,
  Plus,
  Wand2,
  RefreshCw,
  Copy,
  Check,
  Trash2,
  AlertTriangle,
  Download,
  ExternalLink,
  Filter,
} from "lucide-react";
import { useChat } from "../store/chat";
import { useT } from "../i18n";
import {
  fetchLoras,
  refreshLoras,
  loraThumb,
  fetchLoraExamples,
  deleteLora,
  downloadLoraExamples,
  fetchLoraMetaStatus,
  refreshLoraCategories,
  refreshOneLora,
} from "../lib/api";
import ExampleGallery from "./ExampleGallery";
import { copyText } from "../lib/clipboard";

// 篩選：底模（base）與內容分類（category，Civitai 標籤）。沒有值的歸到「未知 / 未分類」。
const BASE_UNKNOWN = "__unknown";
const CAT_NONE = "__none";
const CAT_ORDER = [
  "character", "celebrity", "clothing", "poses", "action", "style", "concept", "background",
  "buildings", "vehicle", "objects", "animal", "tool", "assets", "other", CAT_NONE,
];
const baseKey = (it) => it.base || BASE_UNKNOWN;
const catKey = (it) => it.category || CAT_NONE;
const FILTER_KEY = "loraBrowserFilters"; // 記住上次的篩選（只存在這台瀏覽器）
const loadFilters = () => {
  try {
    return JSON.parse(localStorage.getItem(FILTER_KEY)) || {};
  } catch {
    return {};
  }
};

/**
 * 大型 LoRA 瀏覽器（縮圖牆 + 詳情），與「提示詞歷史」同一套互動，放在 TopBar 歷史按鈕旁。
 * 可依底模與內容分類篩選；點卡片看詳情（大預覽圖 + 觸發詞 + Civitai 來源 + 範例圖與提示詞），
 * 可「帶入」輸入框、「直接生成」或刪除。
 * 直接接 store：insertComposer（附加到輸入框）、generateLora（直接生圖）。
 */
// onInsert / onGenerate 可覆寫動作（漫畫工作室帶入畫風）；不傳則沿用聊天 store 行為。
// onGenerate={null} 可隱藏「直接生成」。
export default function LoraBrowser({ onClose, onInsert, onGenerate }) {
  const t = useT();
  const streaming = useChat((s) => s.streaming);
  const insertComposer = useChat((s) => s.insertComposer);
  const generateLora = useChat((s) => s.generateLora);
  const showGenerate = onGenerate !== null;

  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selected, setSelected] = useState(null);
  const [base, setBase] = useState(() => loadFilters().base || "");
  const [cat, setCat] = useState(() => loadFilters().cat || "");
  const [meta, setMeta] = useState(null); // 分類抓取進度 {total, done, running}
  const qRef = useRef(q);
  qRef.current = q;
  const poll = useRef({ timer: null, lastDone: -1, alive: true });

  useEffect(() => {
    try {
      localStorage.setItem(FILTER_KEY, JSON.stringify({ base, cat }));
    } catch {
      /* 無痕模式等 → 不記 */
    }
  }, [base, cat]);

  // 分類只在按「更新分類」時由後端背景向 Civitai 抓；抓的期間每 3 秒看一次進度，
  // 每多 50 筆（和抓完時）重新載入清單。沒在抓時只拿到「已有分類幾個」
  const pollMeta = useCallback(async () => {
    const p = poll.current;
    clearTimeout(p.timer);
    const m = await fetchLoraMetaStatus().catch(() => null);
    if (!p.alive || !m) return;
    setMeta(m);
    if (p.lastDone >= 0 && (m.done - p.lastDone >= 50 || (!m.running && m.done !== p.lastDone))) {
      p.lastDone = m.done;
      fetchLoras(qRef.current)
        .then((d) => p.alive && setItems(d))
        .catch(() => {});
    }
    if (p.lastDone < 0) p.lastDone = m.done;
    if (m.running) p.timer = setTimeout(pollMeta, 3000);
  }, []);
  useEffect(() => {
    const p = poll.current;
    p.alive = true;
    return () => {
      p.alive = false;
      clearTimeout(p.timer);
    };
  }, []);

  // 搜尋去抖動
  useEffect(() => {
    const id = setTimeout(() => setQ(qInput.trim()), 250);
    return () => clearTimeout(id);
  }, [qInput]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fetchLoras(q) // 不帶 limit → 顯示全部 LoRA
      .then((d) => alive && setItems(d))
      .catch(() => alive && setItems([]))
      .finally(() => {
        if (!alive) return;
        setLoading(false);
        pollMeta(); // 看分類狀態（有沒有正在更新、還有幾個沒有分類）
      });
    return () => {
      alive = false;
    };
  }, [q, pollMeta]);

  // 「更新分類」：全部重新向 Civitai 查；進度從 0 算起，所以輪詢的基準也歸零
  const doRefreshCats = async () => {
    poll.current.lastDone = -1;
    const m = await refreshLoraCategories().catch(() => null);
    if (m) setMeta(m);
    pollMeta();
  };

  const shown = items.filter(
    (it) => (!base || baseKey(it) === base) && (!cat || catKey(it) === cat)
  );

  // 請 A1111 重掃 LoRA 目錄後重新載入
  const doRefresh = async () => {
    setRefreshing(true);
    try {
      await refreshLoras();
      setItems(await fetchLoras(q));
    } catch {
      /* 連不到 A1111 → 維持現狀 */
    } finally {
      setRefreshing(false);
    }
  };

  const doInsert = (c) => {
    if (onInsert) onInsert(c);
    else insertComposer(c.prompt || `<lora:${c.name}:1>`);
    onClose();
  };
  const doGenerate = (c) => {
    if (onGenerate) onGenerate(c);
    else generateLora(c);
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 p-2 sm:p-4"
      onClick={onClose}
    >
      <div
        className="flex h-[92dvh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-ink-700 bg-ink-850 sm:h-[88dvh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 標題列 + 搜尋 */}
        <div className="flex items-center gap-2 border-b border-ink-700 px-4 py-3 sm:gap-3 sm:px-5">
          <h2 className="flex shrink-0 items-center gap-2 text-base font-semibold">
            <Layers size={17} />
            <span className="hidden sm:inline">{t("loras")}</span>
          </h2>
          <div className="relative min-w-0 flex-1">
            <Search
              size={15}
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500"
            />
            <input
              autoFocus
              value={qInput}
              onChange={(e) => setQInput(e.target.value)}
              placeholder={t("loraSearchPh")}
              className="w-full rounded-lg border border-ink-600 bg-ink-800 py-1.5 pl-8 pr-3 text-sm outline-none focus:border-ink-500"
            />
          </div>
          <button
            onClick={doRefresh}
            disabled={refreshing}
            title={t("loraRefresh")}
            className="shrink-0 rounded-lg p-1.5 text-gray-400 hover:bg-ink-750 disabled:opacity-50"
          >
            <RefreshCw size={16} className={refreshing ? "animate-spin" : ""} />
          </button>
          <button
            onClick={onClose}
            className="shrink-0 rounded-lg p-1.5 text-gray-400 hover:bg-ink-750"
          >
            <X size={18} />
          </button>
        </div>

        {/* 內容區：縮圖牆 或 詳情 */}
        {selected ? (
          <LoraDetail
            lora={selected}
            t={t}
            streaming={streaming}
            onBack={() => setSelected(null)}
            onInsert={() => doInsert(selected)}
            onGenerate={() => doGenerate(selected)}
            showGenerate={showGenerate}
            catLabel={(k) => catLabel(k, t)}
            onUpdated={(item) => {
              setSelected(item);
              setItems((list) => list.map((it) => (it.name === item.name ? item : it)));
            }}
            onDeleted={() => {
              setItems((list) => list.filter((it) => it.name !== selected.name));
              setSelected(null);
            }}
          />
        ) : (
          <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-5">
            {loading && (
              <div className="flex items-center justify-center gap-2 py-10 text-sm text-gray-400">
                <Loader2 size={16} className="animate-spin" /> {t("loading")}
              </div>
            )}
            {!loading && items.length === 0 && (
              <div className="py-10 text-center text-sm text-gray-500">
                {t("loraEmpty")}
              </div>
            )}
            {!loading && items.length > 0 && (
              <>
                <FilterBar
                  items={items}
                  base={base}
                  setBase={setBase}
                  cat={cat}
                  setCat={setCat}
                  meta={meta}
                  onRefreshCats={doRefreshCats}
                  t={t}
                />
                <p className="mb-3 text-xs text-gray-500">
                  {t("historyTotal", { count: shown.length })}
                </p>
                {shown.length === 0 && (
                  <div className="py-10 text-center text-sm text-gray-500">
                    {t("loraFilterEmpty")}{" "}
                    <button
                      onClick={() => {
                        setBase("");
                        setCat("");
                      }}
                      className="text-emerald-300 hover:underline"
                    >
                      {t("loraFilterClear")}
                    </button>
                  </div>
                )}
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
                  {shown.map((c, i) => (
                    <LoraCard
                      key={`${c.name}-${i}`}
                      lora={c}
                      onClick={() => setSelected(c)}
                    />
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/** 縮圖牆卡片：縮圖載入失敗（後端 404 = 無預覽圖）顯示首字母佔位塊。 */
function LoraCard({ lora, onClick }) {
  const [broken, setBroken] = useState(false);
  const letter = (lora.alias || lora.name || "?").trim().charAt(0).toUpperCase();
  return (
    <button
      onClick={onClick}
      className="group flex flex-col overflow-hidden rounded-xl border border-ink-700 bg-ink-800 text-left transition hover:border-ink-500"
    >
      <div className="relative aspect-square w-full overflow-hidden bg-ink-900">
        {lora.base && (
          <span
            data-testid="lora-base-badge"
            className="absolute left-1 top-1 z-10 rounded bg-black/65 px-1.5 py-0.5 text-[10px] text-gray-200"
          >
            {lora.base}
          </span>
        )}
        {broken ? (
          <div className="flex h-full flex-col items-center justify-center gap-1 text-gray-600">
            <Layers size={20} />
            <span className="text-lg font-semibold text-gray-500">{letter}</span>
          </div>
        ) : (
          <img
            src={loraThumb(lora.name, 256)}
            alt=""
            loading="lazy"
            onError={() => setBroken(true)}
            className="h-full w-full object-cover transition group-hover:scale-[1.03]"
          />
        )}
      </div>
      <div className="px-2 py-1.5">
        <p className="truncate text-xs text-gray-300" title={lora.alias}>
          {lora.alias}
        </p>
        <p className="mt-0.5 truncate text-[10px] text-gray-600">
          {lora.triggers && lora.triggers.length
            ? lora.triggers.slice(0, 3).join(", ")
            : `<lora:${lora.name}:1>`}
        </p>
      </div>
    </button>
  );
}

function LoraDetail({
  lora,
  t,
  streaming,
  onBack,
  onInsert,
  onGenerate,
  showGenerate = true,
  onDeleted,
  onUpdated,
  catLabel,
}) {
  const [broken, setBroken] = useState(false);
  // 「更新」：{busy, msg, error}；bust＝更新後讓預覽圖重新載入；exTick＝重新載入範例圖
  const [up, setUp] = useState({ busy: false, msg: "", error: "" });
  const [bust, setBust] = useState(0);
  const [exTick, setExTick] = useState(0);
  const [copied, setCopied] = useState(false);
  const letter = (lora.alias || lora.name || "?").trim().charAt(0).toUpperCase();
  // Civitai 範例圖（經 Civitai Helper）：{loading, data, error}
  const [ex, setEx] = useState({ loading: true, data: null, error: "" });
  // 刪除：confirm＝顯示確認列；busy＝刪除中；error＝失敗訊息
  const [del, setDel] = useState({ confirm: false, busy: false, error: "" });

  // 「下載所有範例圖」：{busy, msg, error}
  const [dl, setDl] = useState({ busy: false, msg: "", error: "" });

  useEffect(() => {
    let alive = true;
    setEx({ loading: true, data: null, error: "" });
    setDl({ busy: false, msg: "", error: "" });
    fetchLoraExamples(lora.name)
      .then((data) => alive && setEx({ loading: false, data, error: "" }))
      .catch((e) => alive && setEx({ loading: false, data: null, error: e.message }));
    return () => {
      alive = false;
    };
  }, [lora.name, exTick]);

  useEffect(() => setUp({ busy: false, msg: "", error: "" }), [lora.name]);

  // 重新讀取這個 LoRA 的資料：來源 / 分類 / 作者（後端重抓 Civitai）、預覽圖、範例圖
  const doUpdate = async () => {
    setUp({ busy: true, msg: "", error: "" });
    try {
      const item = await refreshOneLora(lora.name);
      onUpdated?.(item);
      setBroken(false);
      setBust(Date.now());
      setExTick((n) => n + 1);
      setUp({
        busy: false,
        msg: item.civitai_ok === false ? "" : t("loraUpdated"),
        error: item.civitai_ok === false ? t("loraUpdateCivitaiFail") : "",
      });
    } catch (e) {
      setUp({ busy: false, msg: "", error: e.message });
    }
  };

  // 請 Civitai Helper 把範例圖全部存到模型旁邊，完成後重新載入圖庫（改從本機讀）
  const doDownload = async () => {
    setDl({ busy: true, msg: "", error: "" });
    try {
      const r = await downloadLoraExamples(lora.name);
      let msg = t("loraDlDone", { n: r.downloaded, existed: r.existed });
      if (r.skipped_nsfw) msg += t("loraDlSkippedNsfw", { n: r.skipped_nsfw });
      if (r.failed) msg += t("loraDlFailed", { n: r.failed });
      const data = await fetchLoraExamples(lora.name).catch(() => null);
      if (data) setEx({ loading: false, data, error: "" });
      setDl({ busy: false, msg, error: "" });
    } catch (e) {
      setDl({ busy: false, msg: "", error: e.message });
    }
  };

  const doDelete = async () => {
    setDel({ confirm: true, busy: true, error: "" });
    try {
      await deleteLora(lora.name);
      onDeleted?.();
    } catch (e) {
      setDel({ confirm: false, busy: false, error: e.message });
    }
  };
  const info = ex.data;

  const copy = async () => {
    if (!(await copyText(lora.prompt || `<lora:${lora.name}:1>`))) return;
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <>
      <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-5">
        <div className="mb-3 flex items-center gap-2">
          <button
            onClick={onBack}
            className="flex min-w-0 flex-1 items-center gap-1.5 text-left text-sm text-gray-400 hover:text-gray-200"
          >
            <ArrowLeft size={15} className="shrink-0" />
            <span className="truncate">{lora.alias}</span>
          </button>
          {(up.msg || up.error) && (
            <span
              data-testid="lora-update-status"
              className={`min-w-0 truncate text-xs ${up.error ? "text-amber-400" : "text-emerald-300"}`}
              title={up.error || up.msg}
            >
              {up.error || up.msg}
            </span>
          )}
          <button
            onClick={doUpdate}
            disabled={up.busy}
            data-testid="lora-update"
            title={t("loraUpdateHint")}
            className="flex shrink-0 items-center gap-1.5 rounded-lg border border-ink-600 px-2.5 py-1 text-xs text-gray-300 hover:bg-ink-750 disabled:opacity-60"
          >
            <RefreshCw size={13} className={up.busy ? "animate-spin" : ""} />
            {up.busy ? t("loraUpdating") : t("loraUpdate")}
          </button>
        </div>

        <div className="grid gap-4 md:grid-cols-[minmax(0,18rem)_1fr]">
          <div className="mx-auto aspect-square w-full max-w-72 overflow-hidden rounded-lg border border-ink-700 bg-ink-900 md:mx-0">
            {broken ? (
              <div className="flex h-full flex-col items-center justify-center gap-2 text-gray-600">
                <Layers size={28} />
                <span className="text-2xl font-semibold text-gray-500">
                  {letter}
                </span>
              </div>
            ) : (
              <img
                src={loraThumb(lora.name, 512) + (bust ? `&v=${bust}` : "")}
                alt=""
                onError={() => setBroken(true)}
                className="h-full w-full object-cover"
              />
            )}
          </div>

          <div className="space-y-3">
            {/* 帶入用的字串（<lora:name:1> + 觸發詞） */}
            <div className="rounded-lg bg-ink-900 p-2.5">
              <div className="mb-1 flex items-center justify-between">
                <span className="text-xs font-medium text-gray-500">Prompt</span>
                <button
                  onClick={copy}
                  className="flex items-center gap-1 text-xs text-gray-400 hover:text-emerald-300"
                >
                  {copied ? <Check size={12} /> : <Copy size={12} />}
                  {copied ? t("copied") : t("copy")}
                </button>
              </div>
              <p className="max-h-40 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-gray-200">
                {lora.prompt || `<lora:${lora.name}:1>`}
              </p>
            </div>

            {/* 原本是從 Civitai 的哪個模型 / 版本下載的 */}
            <SourceInfo lora={lora} t={t} catLabel={catLabel} />

            {/* 觸發詞清單 */}
            {lora.triggers && lora.triggers.length > 0 && (
              <div className="rounded-lg bg-ink-900 p-2.5">
                <span className="text-xs font-medium text-gray-500">
                  {t("loraTriggers")}
                </span>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {lora.triggers.map((trig, i) => (
                    <span
                      key={`${trig}-${i}`}
                      className="rounded-md bg-ink-800 px-2 py-0.5 text-xs text-gray-300"
                    >
                      {trig}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* 範例圖與提示詞（本地存好的優先，其次 Civitai 縮圖） */}
        <div className="mt-4" data-testid="lora-examples">
          {ex.loading ? (
            <div className="flex items-center gap-2 py-4 text-sm text-gray-400">
              <Loader2 size={15} className="animate-spin" /> {t("loraExamplesLoading")}
            </div>
          ) : ex.error ? (
            <p className="rounded-lg bg-ink-900 px-3 py-2 text-xs text-gray-500">{ex.error}</p>
          ) : info?.items?.length ? (
            <ExampleGallery
              gallery={{
                title: t("loraExamples"),
                trained_words: info.trained_words,
                items: info.items,
              }}
              actions={
                <>
                  {(dl.msg || dl.error) && (
                    <span
                      data-testid="lora-dl-status"
                      className={dl.error ? "text-red-400" : "text-emerald-300"}
                    >
                      {dl.error || dl.msg}
                    </span>
                  )}
                  {info.items.some((it) => !it.local) ? (
                    <button
                      onClick={doDownload}
                      disabled={dl.busy}
                      data-testid="lora-dl-examples"
                      title={t("loraDlHint")}
                      className="flex items-center gap-1 rounded border border-ink-600 px-1.5 py-0.5 text-gray-300 hover:bg-ink-750 disabled:opacity-60"
                    >
                      {dl.busy ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
                      {dl.busy ? t("loraDlBusy") : t("loraDlExamples")}
                    </button>
                  ) : (
                    !dl.msg && <span className="text-gray-500">{t("loraDlAllLocal")}</span>
                  )}
                </>
              }
            />
          ) : (
            <p className="rounded-lg bg-ink-900 px-3 py-2 text-xs text-gray-500">{t("loraExamplesNone")}</p>
          )}
        </div>
      </div>

      {/* 動作列：左邊刪除（先確認），右邊帶入 / 直接生成 */}
      {del.confirm ? (
        <div
          data-testid="lora-delete-confirm"
          className="flex flex-wrap items-center gap-2 border-t border-red-900/60 bg-red-950/30 px-4 py-3 sm:px-5"
        >
          <AlertTriangle size={16} className="shrink-0 text-red-400" />
          <span className="min-w-0 flex-1 text-sm text-red-200">{t("loraDeleteConfirm")}</span>
          <button
            onClick={() => setDel({ confirm: false, busy: false, error: "" })}
            disabled={del.busy}
            className="rounded-lg border border-ink-600 px-4 py-2 text-sm text-gray-200 hover:bg-ink-750 disabled:opacity-50"
          >
            {t("cancel")}
          </button>
          <button
            onClick={doDelete}
            disabled={del.busy}
            data-testid="lora-delete-yes"
            className="flex items-center gap-1.5 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-500 disabled:opacity-60"
          >
            {del.busy ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} />}
            {del.busy ? t("loraDeleting") : t("loraDeleteYes")}
          </button>
        </div>
      ) : (
      <div className="flex items-center justify-end gap-2 border-t border-ink-700 px-4 py-3 sm:px-5">
        <button
          onClick={() => setDel({ confirm: true, busy: false, error: "" })}
          data-testid="lora-delete"
          title={t("loraDelete")}
          className="flex shrink-0 items-center gap-1.5 rounded-lg border border-red-900/60 px-3 py-2 text-sm text-red-300 hover:bg-red-950/40"
        >
          <Trash2 size={15} /> <span className="hidden sm:inline">{t("loraDelete")}</span>
        </button>
        <span
          data-testid="lora-delete-error"
          className="min-w-0 flex-1 truncate text-xs text-red-400"
          title={del.error}
        >
          {del.error}
        </span>
        <button
          onClick={onInsert}
          className="flex items-center gap-1.5 rounded-lg border border-ink-600 px-4 py-2 text-sm font-medium text-gray-200 hover:bg-ink-750"
        >
          <Plus size={15} /> {t("charInsert")}
        </button>
        {showGenerate && (
          <button
            onClick={onGenerate}
            disabled={streaming}
            className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-ink-600 disabled:text-gray-500"
          >
            <Wand2 size={15} /> {t("historyGenerate")}
          </button>
        )}
      </div>
      )}
    </>
  );
}

function catLabel(k, t) {
  return k === CAT_NONE ? t("loraCatNone") : t(`loraCat_${k}`);
}

/** 底模 / 分類兩排篩選。數量彼此連動：選了底模，分類的數量只算那個底模的（反之亦然）。 */
function FilterBar({ items, base, setBase, cat, setCat, meta, onRefreshCats, t }) {
  const tally = (list, key) =>
    list.reduce((m, it) => {
      const k = key(it);
      m[k] = (m[k] || 0) + 1;
      return m;
    }, {});
  const baseCounts = tally(cat ? items.filter((it) => catKey(it) === cat) : items, baseKey);
  const catCounts = tally(base ? items.filter((it) => baseKey(it) === base) : items, catKey);
  const bases = [...new Set([...Object.keys(baseCounts), ...(base ? [base] : [])])].sort(
    (a, b) =>
      (a === BASE_UNKNOWN) - (b === BASE_UNKNOWN) || (baseCounts[b] || 0) - (baseCounts[a] || 0)
  );
  const cats = CAT_ORDER.filter((k) => catCounts[k] || k === cat);
  const loadingCats = meta?.running;

  const chip = (active, label, n, onClick, testid) => (
    <button
      key={testid}
      onClick={onClick}
      data-testid={testid}
      className={`rounded-full border px-2.5 py-0.5 text-xs transition ${
        active
          ? "border-emerald-600/60 bg-emerald-600/20 text-emerald-200"
          : "border-ink-600 text-gray-300 hover:bg-ink-750"
      }`}
    >
      {label}
      <span className={`ml-1 ${active ? "text-emerald-300/80" : "text-gray-500"}`}>{n ?? 0}</span>
    </button>
  );
  const row = (title, children, extra) => (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="flex w-12 shrink-0 items-center gap-1 text-xs text-gray-500">
        <Filter size={11} /> {title}
      </span>
      {children}
      {extra}
    </div>
  );

  return (
    <div data-testid="lora-filters" className="mb-3 space-y-1.5">
      {row(
        t("loraFilterBase"),
        [
          chip(!base, t("loraFilterAll"), Object.values(baseCounts).reduce((a, b) => a + b, 0), () => setBase(""), "base-all"),
          ...bases.map((k) =>
            chip(base === k, k === BASE_UNKNOWN ? t("loraBaseUnknown") : k, baseCounts[k], () => setBase(base === k ? "" : k), `base-${k}`)
          ),
        ]
      )}
      {row(
        t("loraFilterCategory"),
        [
          chip(!cat, t("loraFilterAll"), Object.values(catCounts).reduce((a, b) => a + b, 0), () => setCat(""), "cat-all"),
          ...cats.map((k) =>
            chip(cat === k, catLabel(k, t), catCounts[k], () => setCat(cat === k ? "" : k), `cat-${k}`)
          ),
        ],
        loadingCats ? (
          <span data-testid="lora-cat-progress" className="flex items-center gap-1 text-[11px] text-gray-500">
            <Loader2 size={11} className="animate-spin" />
            {t("loraCatLoading", { done: meta.done, total: meta.total })}
          </span>
        ) : (
          <>
            <button
              onClick={onRefreshCats}
              data-testid="lora-cat-refresh"
              title={t("loraCatRefreshHint")}
              className="flex items-center gap-1 rounded-full border border-ink-600 px-2.5 py-0.5 text-xs text-gray-400 hover:bg-ink-750 hover:text-gray-200"
            >
              <RefreshCw size={11} /> {t("loraCatRefresh")}
            </button>
            {meta?.failed > 0 && (
              <span className="text-[11px] text-amber-400">{t("loraCatFailed", { n: meta.failed })}</span>
            )}
            {meta && meta.done < meta.total && (
              <span data-testid="lora-cat-missing" className="text-[11px] text-gray-500">
                {t("loraCatMissing", { n: meta.total - meta.done })}
              </span>
            )}
          </>
        )
      )}
    </div>
  );
}

/** Civitai 來源：這個 LoRA 原本是從 Civitai 的哪個模型 / 版本下載的。 */
function SourceInfo({ lora, t, catLabel }) {
  const s = lora.source;
  const tag = (text) => (
    <span className="rounded-md bg-ink-800 px-1.5 py-0.5">{text}</span>
  );
  if (!s) {
    return (
      <div data-testid="lora-source" className="rounded-lg bg-ink-900 p-2.5 text-xs">
        <span className="font-medium text-gray-500">{t("loraSource")}</span>
        <p className="mt-1 text-gray-500">{t("loraSourceNone")}</p>
        {lora.base && (
          <p className="mt-1.5 text-gray-300">
            {tag(`${t("loraBaseModel")}: ${lora.base}${lora.base_inferred ? ` ${t("loraBaseInferred")}` : ""}`)}
          </p>
        )}
      </div>
    );
  }
  return (
    <div data-testid="lora-source" className="rounded-lg bg-ink-900 p-2.5">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-gray-500">{t("loraSource")}</span>
        <a
          href={s.url}
          target="_blank"
          rel="noreferrer"
          className="flex shrink-0 items-center gap-1 text-xs text-sky-300 hover:text-sky-200"
        >
          <ExternalLink size={12} /> {t("loraOpenCivitai")}
        </a>
      </div>
      <a
        href={s.url}
        target="_blank"
        rel="noreferrer"
        className="break-words text-sm font-medium text-gray-100 hover:underline"
      >
        {s.model_name}
      </a>
      {s.version_name && <span className="ml-1.5 text-xs text-gray-400">· {s.version_name}</span>}
      <div className="mt-1.5 flex flex-wrap gap-1.5 text-[11px] text-gray-300">
        {s.creator && tag(`${t("loraCreator")}: ${s.creator}`)}
        {s.type && tag(`${t("loraType")}: ${s.type}`)}
        {s.base_model && tag(`${t("loraBaseModel")}: ${s.base_model}`)}
        {lora.category && tag(`${t("loraFilterCategory")}: ${catLabel(lora.category)}`)}
      </div>
      <p className="mt-1.5 text-[10px] text-gray-600">
        {t("loraModelId")} {s.model_id}
        {s.version_id ? ` · ${t("loraVersionId")} ${s.version_id}` : ""} · {s.host}
      </p>
    </div>
  );
}
