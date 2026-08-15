import { useState, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { appSettingsApi } from "../../api";
import { Mail, Clock, ShieldCheck, ShieldAlert, Send, Lock } from "lucide-react";

const SECRET_PLACEHOLDER = "********";
const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

// Why some settings are read-only here, shown to the user rather than left as
// an unexplained gap. Each one is either needed before the settings table can
// be read, or would break the session doing the editing.
const ENV_ONLY_REASON: Record<string, string> = {
  JWT_SECRET: "Rotating this signs you out mid-save, with no way to confirm it worked.",
  DATABASE_URL: "This is how the settings table is reached, so it can't live inside it.",
  ALLOWED_ORIGINS: "A CORS allowlist editable from a browser would be a CSRF foothold.",
  HOST: "Applied when the server binds; changing it at runtime would do nothing.",
  PORT: "Applied when the server binds; changing it at runtime would do nothing.",
  APP_ENCRYPTION_KEY: "Changing it makes every stored secret undecryptable, including bank tokens.",
};

export default function NotificationsTab() {
  const qc = useQueryClient();
  const { data: cfg, isLoading, isError } = useQuery({ queryKey: ["app-settings"], queryFn: appSettingsApi.get });

  const [form, setForm] = useState<Record<string, any>>({});
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);

  useEffect(() => {
    if (!cfg) return;
    setForm({
      smtp_host: cfg.smtp_host ?? "",
      smtp_port: cfg.smtp_port ?? 587,
      smtp_user: cfg.smtp_user ?? "",
      // The server never sends the password back, so seed the mask. The PATCH
      // handler drops this exact value, meaning an untouched field is a no-op
      // rather than overwriting the stored secret with asterisks.
      smtp_pass: cfg.smtp_pass_set ? SECRET_PLACEHOLDER : "",
      smtp_from: cfg.smtp_from ?? "",
      daily_summary_hour: cfg.daily_summary_hour ?? 7,
      weekly_digest_day: cfg.weekly_digest_day ?? "fri",
      weekly_digest_enabled: !!cfg.weekly_digest_enabled,
      report_recipients: cfg.report_recipients ?? "",
    });
    setDirty(false);
  }, [cfg]);

  function set(key: string, value: any) {
    setForm((f) => ({ ...f, [key]: value }));
    setDirty(true);
    setSaved(false);
  }

  const saveMut = useMutation({
    mutationFn: appSettingsApi.update,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["app-settings"] });
      setDirty(false);
      setSaved(true);
    },
  });

  const testMut = useMutation({
    mutationFn: appSettingsApi.testEmail,
    onSuccess: (r: any) => {
      const sent = (r?.sent_to ?? []).join(", ");
      const errs = (r?.errors ?? []).join("; ");
      setTestResult(errs ? `Sent to ${sent || "nobody"}. Failed: ${errs}` : `Sent to ${sent}`);
    },
    onError: () => setTestResult(null), // the global toast already reports it
  });

  if (isLoading) return <div className="card"><p className="text-sm text-gray-400">Loading…</p></div>;
  if (isError) {
    return (
      <div className="card">
        <h3 className="font-semibold text-gray-900 dark:text-gray-100 mb-1">Notifications &amp; Email</h3>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Couldn't load server settings. These are admin-only, so this is expected if your account isn't an admin.
        </p>
      </div>
    );
  }

  const recipientCount = String(form.report_recipients ?? "")
    .split(",").map((s) => s.trim()).filter(Boolean).length;

  return (
    <div className="space-y-6">
      <div className="card">
        <div className="flex items-center gap-2 mb-1">
          <Mail size={16} className="text-indigo-500" />
          <h3 className="font-semibold text-gray-900 dark:text-gray-100">Daily Report Recipients</h3>
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
          Everyone who should receive the daily summary. Separate addresses with commas — they don't need
          accounts in the app. Leave blank to fall back to your own account email.
        </p>
        <textarea
          className="input w-full text-sm font-mono"
          rows={2}
          placeholder="you@example.com, spouse@example.com"
          value={form.report_recipients ?? ""}
          onChange={(e) => set("report_recipients", e.target.value)}
        />
        <p className="text-xs text-gray-400 mt-1">
          {recipientCount > 0
            ? `${recipientCount} recipient${recipientCount === 1 ? "" : "s"}`
            : "No recipients set — falling back to your account email"}
        </p>
      </div>

      <div className="card">
        <div className="flex items-center gap-2 mb-3">
          <Clock size={16} className="text-indigo-500" />
          <h3 className="font-semibold text-gray-900 dark:text-gray-100">Schedule</h3>
        </div>
        <div className="grid sm:grid-cols-2 gap-4">
          <label className="block">
            <span className="label">Daily summary hour</span>
            <select className="input" value={form.daily_summary_hour ?? 7}
              onChange={(e) => set("daily_summary_hour", parseInt(e.target.value))}>
              {Array.from({ length: 24 }, (_, h) => (
                <option key={h} value={h}>
                  {h === 0 ? "12:00 AM" : h < 12 ? `${h}:00 AM` : h === 12 ? "12:00 PM" : `${h - 12}:00 PM`}
                </option>
              ))}
            </select>
            <span className="text-xs text-gray-400">Server local time</span>
          </label>
          <label className="block">
            <span className="label">Weekly digest day</span>
            <select className="input" value={form.weekly_digest_day ?? "fri"}
              onChange={(e) => set("weekly_digest_day", e.target.value)}
              disabled={!form.weekly_digest_enabled}>
              {DAYS.map((d) => <option key={d} value={d}>{d[0].toUpperCase() + d.slice(1)}</option>)}
            </select>
            <span className="text-xs text-gray-400">Spending + merchants ride along that day</span>
          </label>
        </div>
        <div className="flex items-center justify-between pt-3 mt-3 border-t border-gray-100 dark:border-gray-700">
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Weekly digest enabled</span>
          <button
            onClick={() => set("weekly_digest_enabled", !form.weekly_digest_enabled)}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${form.weekly_digest_enabled ? "bg-indigo-600" : "bg-gray-200"}`}
          >
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${form.weekly_digest_enabled ? "translate-x-6" : "translate-x-1"}`} />
          </button>
        </div>
      </div>

      <div className="card">
        <div className="flex items-center gap-2 mb-1">
          <Send size={16} className="text-indigo-500" />
          <h3 className="font-semibold text-gray-900 dark:text-gray-100">Mail Server (SMTP)</h3>
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
          Without this, no email sends at all. For Gmail use an app password, not your account password.
        </p>
        <div className="grid sm:grid-cols-2 gap-4">
          <label className="block sm:col-span-2">
            <span className="label">Host</span>
            <input className="input" placeholder="smtp.gmail.com" value={form.smtp_host ?? ""}
              onChange={(e) => set("smtp_host", e.target.value)} />
          </label>
          <label className="block">
            <span className="label">Port</span>
            <input type="number" className="input" value={form.smtp_port ?? 587}
              onChange={(e) => set("smtp_port", parseInt(e.target.value) || 587)} />
          </label>
          <label className="block">
            <span className="label">Username</span>
            <input className="input" autoComplete="off" value={form.smtp_user ?? ""}
              onChange={(e) => set("smtp_user", e.target.value)} />
          </label>
          <label className="block sm:col-span-2">
            <span className="label flex items-center gap-1.5">
              Password <Lock size={11} className="text-gray-400" />
            </span>
            <input
              type="password"
              className="input"
              autoComplete="new-password"
              value={form.smtp_pass ?? ""}
              onFocus={(e) => { if (e.target.value === SECRET_PLACEHOLDER) set("smtp_pass", ""); }}
              onChange={(e) => set("smtp_pass", e.target.value)}
            />
            <span className="text-xs text-gray-400">
              Encrypted before storage and never sent back to this page.
            </span>
          </label>
          <label className="block sm:col-span-2">
            <span className="label">From address</span>
            <input className="input" placeholder="OfflineBudget &lt;you@example.com&gt;"
              value={form.smtp_from ?? ""} onChange={(e) => set("smtp_from", e.target.value)} />
          </label>
        </div>

        {!cfg.encryption_configured && (
          <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-2.5 dark:border-amber-900/60 dark:bg-amber-950/40">
            <ShieldAlert size={14} className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" />
            <p className="text-xs text-amber-800 dark:text-amber-200">
              No encryption key set, so the password can't be saved. Add <code>APP_ENCRYPTION_KEY</code> to
              your <code>.env</code> and restart. Storing it unencrypted isn't offered on purpose.
            </p>
          </div>
        )}

        <div className="flex items-center gap-3 mt-4 pt-3 border-t border-gray-100 dark:border-gray-700">
          <button className="btn-primary" disabled={!dirty || saveMut.isPending}
            onClick={() => saveMut.mutate(form)}>
            {saveMut.isPending ? "Saving…" : "Save settings"}
          </button>
          <button className="btn-secondary" disabled={testMut.isPending || !cfg.smtp_host}
            title={!cfg.smtp_host ? "Save an SMTP host first" : "Send a real test email"}
            onClick={() => { setTestResult(null); testMut.mutate(); }}>
            {testMut.isPending ? "Sending…" : "Send test email"}
          </button>
          {saved && <span className="text-xs text-emerald-600 dark:text-emerald-400">Saved</span>}
          {dirty && <span className="text-xs text-amber-600 dark:text-amber-400">Unsaved changes</span>}
        </div>
        {testResult && <p className="text-xs text-gray-500 dark:text-gray-400 mt-2">{testResult}</p>}
      </div>

      <div className="card">
        <div className="flex items-center gap-2 mb-1">
          <ShieldCheck size={16} className="text-gray-400" />
          <h3 className="font-semibold text-gray-900 dark:text-gray-100">Server Configuration</h3>
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
          Set in <code>.env</code> and intentionally not editable here. Status only — values are never
          sent to the browser.
        </p>
        <div className="space-y-1.5">
          {(cfg.env_status ?? []).map((e: any) => (
            <div key={e.key} className="flex items-start justify-between gap-4 py-1.5 border-b border-gray-50 dark:border-gray-800 last:border-0">
              <div className="min-w-0">
                <code className="text-xs text-gray-700 dark:text-gray-300">{e.key}</code>
                {ENV_ONLY_REASON[e.key] && (
                  <p className="text-xs text-gray-400 mt-0.5">{ENV_ONLY_REASON[e.key]}</p>
                )}
              </div>
              <span className={`shrink-0 text-xs px-1.5 py-0.5 rounded ${e.configured
                ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"
                : "bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400"}`}>
                {e.configured ? "configured" : "not set"}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
