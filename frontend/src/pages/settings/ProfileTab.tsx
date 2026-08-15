import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { authApi } from "../../api";
import { User, Mail, KeyRound } from "lucide-react";
import { parseServerDateTime } from "../../lib/utils";

export default function ProfileTab() {
  const qc = useQueryClient();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: authApi.me });
  const [profileName, setProfileName] = useState("");
  const [profileSaved, setProfileSaved] = useState(false);
  const [pwForm, setPwForm] = useState({ current: "", next: "", confirm: "" });
  const [pwError, setPwError] = useState<string | null>(null);
  const [pwSaved, setPwSaved] = useState(false);
  const [profileEmail, setProfileEmail] = useState("");
  const [testEmailStatus, setTestEmailStatus] = useState<"idle" | "sending" | "ok" | "err">("idle");
  const [recoveryCode, setRecoveryCode] = useState<string | null>(null);
  const [recoveryCodeStatus, setRecoveryCodeStatus] = useState<"idle" | "generating" | "ok" | "err">("idle");
  const [recoveryCodeCopied, setRecoveryCodeCopied] = useState(false);
  const [recoveryCodeCopyError, setRecoveryCodeCopyError] = useState(false);
  const generateRecoveryCodeMut = useMutation({
    mutationFn: authApi.generateRecoveryCode,
    onMutate: () => setRecoveryCodeStatus("generating"),
    onSuccess: (data) => {
      setRecoveryCode(data.code);
      setRecoveryCodeStatus("ok");
      qc.invalidateQueries({ queryKey: ["me"] });
    },
    onError: () => { setRecoveryCodeStatus("err"); setTimeout(() => setRecoveryCodeStatus("idle"), 3000); },
  });

  React.useEffect(() => {
    if (me) {
      setProfileName(me.display_name ?? "");
      setProfileEmail(me.email ?? "");
    }
  }, [me]);
  const updateMeMut = useMutation({
    mutationFn: authApi.updateMe,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["me"] }); setProfileSaved(true); setTimeout(() => setProfileSaved(false), 2000); },
  });
  const sendTestEmailMut = useMutation({
    mutationFn: authApi.sendTestEmail,
    onMutate: () => setTestEmailStatus("sending"),
    onSuccess: () => { setTestEmailStatus("ok"); setTimeout(() => setTestEmailStatus("idle"), 3000); },
    onError: () => { setTestEmailStatus("err"); setTimeout(() => setTestEmailStatus("idle"), 3000); },
  });
  const changePasswordMut = useMutation({
    mutationFn: authApi.changePassword,
    onSuccess: () => { setPwForm({ current: "", next: "", confirm: "" }); setPwError(null); setPwSaved(true); setTimeout(() => setPwSaved(false), 2000); },
    onError: (e: any) => setPwError(e?.response?.data?.detail ?? "Failed to change password"),
  });
  function submitPassword(e: React.FormEvent) {
    e.preventDefault();
    if (pwForm.next !== pwForm.confirm) { setPwError("New passwords don't match"); return; }
    if (pwForm.next.length < 6) { setPwError("Password must be at least 6 characters"); return; }
    setPwError(null);
    changePasswordMut.mutate({ current_password: pwForm.current, new_password: pwForm.next });
  }

  return (
    <div className="card">
      <h3 className="font-semibold text-gray-900 dark:text-gray-100 flex items-center gap-2 mb-4"><User size={16} className="text-indigo-500" /> Profile</h3>
      <div className="space-y-5">
        <div className="flex items-end gap-3">
          <div className="flex-1 max-w-xs">
            <label className="label">Display Name</label>
            <input className="input" value={profileName} onChange={e => setProfileName(e.target.value)} placeholder="Your name" />
          </div>
          <button
            onClick={() => updateMeMut.mutate({ display_name: profileName })}
            disabled={updateMeMut.isPending || !profileName.trim()}
            className="btn-primary text-sm"
          >
            {updateMeMut.isPending ? "Saving…" : "Save"}
          </button>
          {profileSaved && <span className="text-sm text-green-600">Saved!</span>}
        </div>
        <div className="space-y-2">
          <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 flex items-center gap-2"><Mail size={14} /> Email Notifications</h4>
          <p className="text-xs text-gray-500 dark:text-gray-400">Used for daily summary emails. Requires SMTP to be configured on the server. Enter multiple addresses separated by commas to send to more than one person.</p>
          <div className="flex items-end gap-3">
            <div className="flex-1 max-w-xs">
              <label className="label">Email Address(es)</label>
              <input type="email" multiple className="input" value={profileEmail} onChange={e => setProfileEmail(e.target.value)} placeholder="you@example.com, spouse@example.com" />
            </div>
            <button
              onClick={() => updateMeMut.mutate({ email: profileEmail || null })}
              disabled={updateMeMut.isPending}
              className="btn-primary text-sm"
            >
              Save
            </button>
            <button
              onClick={() => sendTestEmailMut.mutate()}
              disabled={sendTestEmailMut.isPending || !me?.email}
              className="btn-secondary text-sm"
              title={!me?.email ? "Save an email address first" : "Send a test email"}
            >
              {testEmailStatus === "sending" ? "Sending…" : testEmailStatus === "ok" ? "Sent!" : testEmailStatus === "err" ? "Failed" : "Test"}
            </button>
          </div>
        </div>
        <div className="pt-2 border-t">
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
            A recovery code lets you reset your password without email. Generating a new one
            replaces any existing code.
          </p>
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
            {me?.recovery_code_created_at
              ? `Recovery code generated on ${parseServerDateTime(me.recovery_code_created_at).toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric" })}`
              : "No recovery code set"}
          </p>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => generateRecoveryCodeMut.mutate()}
            disabled={generateRecoveryCodeMut.isPending}
          >
            {recoveryCodeStatus === "generating" ? "Generating…" : "Generate Recovery Code"}
          </button>
          {recoveryCodeStatus === "err" && (
            <span className="ml-2 text-sm text-red-600">Failed to generate a recovery code. Try again.</span>
          )}
        </div>

        {recoveryCode && (
          <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
            <div className="card max-w-sm w-full space-y-4">
              <h3 className="font-semibold text-gray-900">Save Your Recovery Code</h3>
              <p className="text-sm text-gray-500">
                This won't be shown again. Store it somewhere safe — it's the only way to reset
                your password without email.
              </p>
              <code className="block text-center text-lg font-mono bg-gray-100 rounded-lg py-3 tracking-wider">
                {recoveryCode}
              </code>
              <button
                type="button"
                className="btn-primary w-full"
                onClick={async () => {
                  try {
                    if (!navigator.clipboard) throw new Error("Clipboard API unavailable");
                    await navigator.clipboard.writeText(recoveryCode);
                    setRecoveryCodeCopied(true);
                    setRecoveryCodeCopyError(false);
                    setTimeout(() => setRecoveryCodeCopied(false), 2000);
                  } catch {
                    setRecoveryCodeCopied(false);
                    setRecoveryCodeCopyError(true);
                  }
                }}
              >
                {recoveryCodeCopied ? "Copied!" : "Copy to Clipboard"}
              </button>
              {recoveryCodeCopyError && (
                <p className="text-sm text-red-600 text-center -mt-2">
                  Couldn't copy automatically — select the code above and copy it manually.
                </p>
              )}
              <button
                type="button"
                className="text-sm text-gray-500 w-full text-center"
                onClick={() => {
                  setRecoveryCode(null);
                  setRecoveryCodeCopied(false);
                  setRecoveryCodeCopyError(false);
                  setRecoveryCodeStatus("idle");
                }}
              >
                I've saved it — close
              </button>
            </div>
          </div>
        )}

        <form onSubmit={submitPassword} className="space-y-3 border-t border-gray-100 dark:border-gray-700 pt-4">
          <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 flex items-center gap-2"><KeyRound size={14} /> Change Password</h4>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 max-w-xl">
            <div>
              <label className="label">Current Password</label>
              <input type="password" className="input" value={pwForm.current} onChange={e => setPwForm({ ...pwForm, current: e.target.value })} required />
            </div>
            <div>
              <label className="label">New Password</label>
              <input type="password" className="input" value={pwForm.next} onChange={e => setPwForm({ ...pwForm, next: e.target.value })} required />
            </div>
            <div>
              <label className="label">Confirm New Password</label>
              <input type="password" className="input" value={pwForm.confirm} onChange={e => setPwForm({ ...pwForm, confirm: e.target.value })} required />
            </div>
          </div>
          {pwError && <p className="text-sm text-red-600">{pwError}</p>}
          {pwSaved && <p className="text-sm text-green-600">Password changed!</p>}
          <button type="submit" disabled={changePasswordMut.isPending} className="btn-primary text-sm">
            {changePasswordMut.isPending ? "Updating…" : "Update Password"}
          </button>
        </form>
      </div>
    </div>
  );
}
