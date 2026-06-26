import { useState } from "react";
import {
  X,
  Sparkles,
  Check,
  Eye,
  Loader2,
  Ban,
  Wand2,
  Plus,
  Pencil,
  Trash2,
  Save,
  ArrowLeft,
  AlertCircle,
} from "lucide-react";
import { useChat } from "../store/chat";
import { useT } from "../i18n";
import {
  fetchSkill,
  createSkill,
  updateSkill,
  deleteSkill,
} from "../lib/api";

const NEW_TEMPLATE = `---
name: My Skill
description: One line — what it does and WHEN the model should use it.
---

# My Skill

Write the instructions the model should follow when this skill is active.
Generate images with the app's built-in image tool (local Stable Diffusion).
`;

/**
 * 技能（Agent Skills）選擇器 + 管理。
 * - 選定的技能會注入到目前引擎的 system prompt（全引擎通用），出圖仍走 A1111。
 * - 「自動」讓模型自行判斷要不要用、用哪個。
 * - 可在網頁直接新增 / 編輯 / 刪除 SKILL.md。
 */
export default function SkillPicker({ onClose }) {
  const t = useT();
  const skills = useChat((s) => s.skills);
  const active = useChat((s) => s.settings.skill) || "";
  const setSettings = useChat((s) => s.setSettings);
  const reloadSkills = useChat((s) => s.reloadSkills);

  const [mode, setMode] = useState("list"); // list | edit
  const [editor, setEditor] = useState(null); // {slug, content, isNew}
  const [viewing, setViewing] = useState(null);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const choose = (slug) => setSettings({ skill: slug });

  const toggleView = async (slug) => {
    if (viewing === slug) return setViewing(null);
    setViewing(slug);
    if (detail?.slug === slug) return;
    setLoading(true);
    try {
      const d = await fetchSkill(slug);
      setDetail({ slug, body: d.body || "" });
    } catch {
      setDetail({ slug, body: "(load failed)" });
    } finally {
      setLoading(false);
    }
  };

  const openNew = () => {
    setErr("");
    setEditor({ slug: "", content: NEW_TEMPLATE, isNew: true });
    setMode("edit");
  };

  const openEdit = async (slug) => {
    setErr("");
    setBusy(true);
    try {
      const d = await fetchSkill(slug);
      setEditor({ slug, content: d.raw || "", isNew: false });
      setMode("edit");
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    setErr("");
    const slug = editor.slug.trim();
    if (!slug || !editor.content.trim()) return;
    setBusy(true);
    try {
      if (editor.isNew) await createSkill(slug, editor.content);
      else await updateSkill(slug, editor.content);
      await reloadSkills();
      setMode("list");
      setEditor(null);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (s) => {
    if (!window.confirm(t("skillDeleteConfirm", { name: s.name }))) return;
    setBusy(true);
    setErr("");
    try {
      await deleteSkill(s.slug);
      await reloadSkills();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/65 p-2 sm:p-4"
      onClick={onClose}
    >
      <div
        className="flex h-[82dvh] w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-ink-700 bg-ink-850"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-ink-700 px-4 py-3">
          {mode === "edit" && (
            <button
              onClick={() => {
                setMode("list");
                setEditor(null);
                setErr("");
              }}
              className="shrink-0 rounded-lg p-1.5 text-gray-400 hover:bg-ink-750"
            >
              <ArrowLeft size={18} />
            </button>
          )}
          <h2 className="flex flex-1 items-center gap-2 text-base font-semibold">
            <Sparkles size={17} /> {t("skills")}
          </h2>
          {mode === "list" && (
            <button
              onClick={openNew}
              className="flex shrink-0 items-center gap-1 rounded-lg border border-ink-600 px-2 py-1 text-xs text-gray-200 hover:bg-ink-750"
            >
              <Plus size={14} /> {t("skillNew")}
            </button>
          )}
          <button
            onClick={onClose}
            className="shrink-0 rounded-lg p-1.5 text-gray-400 hover:bg-ink-750"
          >
            <X size={18} />
          </button>
        </div>

        {err && (
          <div className="flex items-start gap-1.5 border-b border-ink-700 bg-red-950/40 px-4 py-2 text-xs text-red-300">
            <AlertCircle size={14} className="mt-0.5 shrink-0" /> {err}
          </div>
        )}

        {mode === "edit" ? (
          <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-3">
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-gray-400">
                {t("skillSlug")}
              </span>
              <input
                value={editor.slug}
                disabled={!editor.isNew}
                onChange={(e) =>
                  setEditor((ed) => ({
                    ...ed,
                    slug: e.target.value.replace(/[^a-zA-Z0-9_-]/g, "-"),
                  }))
                }
                placeholder={t("skillSlugPh")}
                className="w-full rounded-md border border-ink-600 bg-ink-800 px-2 py-1.5 text-sm outline-none focus:border-ink-500 disabled:opacity-60"
              />
            </label>
            <label className="flex min-h-0 flex-1 flex-col">
              <span className="mb-1 block text-xs font-medium text-gray-400">
                {t("skillContent")}
              </span>
              <textarea
                value={editor.content}
                onChange={(e) =>
                  setEditor((ed) => ({ ...ed, content: e.target.value }))
                }
                spellCheck={false}
                className="min-h-[16rem] flex-1 resize-none rounded-md border border-ink-600 bg-ink-900 p-2 font-mono text-xs leading-relaxed outline-none focus:border-ink-500"
              />
            </label>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => {
                  setMode("list");
                  setEditor(null);
                  setErr("");
                }}
                className="rounded-lg border border-ink-600 px-3 py-1.5 text-sm text-gray-300 hover:bg-ink-750"
              >
                {t("skillCancel")}
              </button>
              <button
                onClick={save}
                disabled={busy || !editor.slug.trim() || !editor.content.trim()}
                className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-ink-600 disabled:text-gray-500"
              >
                {busy ? (
                  <Loader2 size={15} className="animate-spin" />
                ) : (
                  <Save size={15} />
                )}
                {t("skillSave")}
              </button>
            </div>
          </div>
        ) : (
          <>
            <p className="border-b border-ink-700 px-4 py-2 text-xs leading-snug text-gray-500">
              {t("skillHint")}
            </p>
            <div className="flex-1 overflow-y-auto p-2">
              {/* 不啟用 */}
              <Row
                icon={<Ban size={15} className="text-gray-400" />}
                label={t("skillNone")}
                on={active === ""}
                onClick={() => choose("")}
              />
              {/* 自動 */}
              <Row
                icon={<Wand2 size={15} className="text-violet-300" />}
                label={t("skillAuto")}
                desc={t("skillAutoDesc")}
                on={active === "__auto__"}
                onClick={() => choose("__auto__")}
              />

              {skills.length === 0 && (
                <p className="px-3 py-8 text-center text-sm text-gray-500">
                  {t("skillEmpty")}
                </p>
              )}

              {skills.map((s) => {
                const on = active === s.slug;
                return (
                  <div
                    key={s.slug}
                    className={`mt-2 rounded-lg border ${
                      on ? "border-emerald-600/60 bg-emerald-600/10" : "border-ink-700"
                    }`}
                  >
                    <div className="p-3">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate font-medium text-gray-100">
                          {s.name}
                        </span>
                        {on && (
                          <span className="shrink-0 rounded bg-emerald-600/20 px-1.5 py-0.5 text-[10px] text-emerald-300">
                            {t("skillActive")}
                          </span>
                        )}
                      </div>
                      {s.description && (
                        <p className="mt-0.5 line-clamp-3 text-xs leading-snug text-gray-500">
                          {s.description}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5 border-t border-ink-700/60 px-3 py-2">
                      <button
                        onClick={() => choose(on ? "" : s.slug)}
                        className={`flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium ${
                          on
                            ? "bg-ink-700 text-gray-200 hover:bg-ink-600"
                            : "bg-emerald-600 text-white hover:bg-emerald-500"
                        }`}
                      >
                        {on ? (
                          <>
                            <Check size={13} /> {t("skillActive")}
                          </>
                        ) : (
                          t("skillActivate")
                        )}
                      </button>
                      <button
                        onClick={() => toggleView(s.slug)}
                        className="flex items-center gap-1 rounded-md border border-ink-600 px-2 py-1 text-xs text-gray-300 hover:bg-ink-750"
                      >
                        <Eye size={13} /> {t("skillView")}
                      </button>
                      <div className="flex-1" />
                      <button
                        onClick={() => openEdit(s.slug)}
                        disabled={busy}
                        title={t("skillEdit")}
                        className="rounded-md p-1.5 text-gray-400 hover:bg-ink-750 hover:text-gray-200 disabled:opacity-50"
                      >
                        <Pencil size={14} />
                      </button>
                      <button
                        onClick={() => remove(s)}
                        disabled={busy}
                        title={t("skillDelete")}
                        className="rounded-md p-1.5 text-gray-500 hover:bg-ink-750 hover:text-red-400 disabled:opacity-50"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                    {viewing === s.slug && (
                      <div className="border-t border-ink-700/60 p-2">
                        {loading && detail?.slug !== s.slug ? (
                          <div className="flex items-center gap-2 px-1 py-3 text-xs text-gray-400">
                            <Loader2 size={14} className="animate-spin" />
                            {t("loading")}
                          </div>
                        ) : (
                          <pre className="max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-md bg-ink-900 p-2 text-[11px] leading-relaxed text-gray-300">
                            {detail?.slug === s.slug ? detail.body : ""}
                          </pre>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Row({ icon, label, desc, on, onClick }) {
  return (
    <button
      onClick={onClick}
      className={`mt-2 flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left text-sm transition first:mt-0 ${
        on ? "border-emerald-600/60 bg-emerald-600/15" : "border-ink-700 hover:bg-ink-800"
      }`}
    >
      <span className="shrink-0">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-gray-200">{label}</span>
        {desc && <span className="block text-xs text-gray-500">{desc}</span>}
      </span>
      {on && <Check size={16} className="shrink-0 text-emerald-400" />}
    </button>
  );
}
