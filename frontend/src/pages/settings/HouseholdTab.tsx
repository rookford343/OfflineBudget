import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { adminApi, authApi } from "../../api";
import { isAdmin } from "../../store/auth";
import { Shield, Activity, User, Link, Plus, RotateCcw, Trash2, X } from "lucide-react";
import { parseServerDateTime } from "../../lib/utils";

const emptyUser = { username: "", display_name: "", password: "", role: "viewer", linked_to_user_id: "" };

export default function HouseholdTab() {
  const qc = useQueryClient();
  const admin = isAdmin();
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: authApi.me });
  const { data: users = [] } = useQuery<any[]>({ queryKey: ["admin-users"], queryFn: adminApi.listUsers, enabled: admin });
  const [logPage, setLogPage] = useState(0);
  const [logMethod, setLogMethod] = useState("");
  const { data: logData } = useQuery<any>({
    queryKey: ["audit-logs", logPage, logMethod],
    queryFn: () => adminApi.logs({ limit: 25, offset: logPage * 25, method: logMethod || undefined }),
    enabled: admin,
  });

  const [showUserForm, setShowUserForm] = useState(false);
  const [userForm, setUserForm] = useState({ ...emptyUser });
  const [resetPwUserId, setResetPwUserId] = useState<number | null>(null);
  const [resetPwValue, setResetPwValue] = useState("");
  const [resetPwError, setResetPwError] = useState<string | null>(null);
  const createUserMut = useMutation({ mutationFn: adminApi.createUser, onSuccess: () => { qc.invalidateQueries({ queryKey: ["admin-users"] }); setShowUserForm(false); setUserForm({ ...emptyUser }); } });
  const updateUserMut = useMutation({ mutationFn: ({ id, data }: any) => adminApi.updateUser(id, data), onSuccess: () => { qc.invalidateQueries({ queryKey: ["admin-users"] }); } });
  const removeUserMut = useMutation({ mutationFn: adminApi.removeUser, onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }) });
  const resetPwMut = useMutation({
    mutationFn: ({ id, pw }: { id: number; pw: string }) => adminApi.resetPassword(id, pw),
    onSuccess: () => { setResetPwUserId(null); setResetPwValue(""); setResetPwError(null); },
    onError: (e: any) => setResetPwError(e?.response?.data?.detail ?? "Failed to reset password"),
  });

  if (!admin) {
    return <div className="card"><p className="text-sm text-gray-500 dark:text-gray-400">Admin access required.</p></div>;
  }

  return (
    <div className="space-y-6">
      {/* ── Users ── */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100 flex items-center gap-2"><Shield size={16} className="text-indigo-500" /> Users</h3>
          <button onClick={() => setShowUserForm(true)} className="btn-primary btn-sm text-xs px-3 py-1.5"><Plus size={14} /> Add User</button>
        </div>
        <div className="divide-y divide-gray-100 dark:divide-gray-700">
          {users.map((u: any) => {
            const linkedTo = u.linked_to_user_id ? users.find((x: any) => x.id === u.linked_to_user_id) : null;
            return (
              <div key={u.id} className="py-3 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 bg-gray-100 dark:bg-gray-700 rounded-full flex items-center justify-center">
                    {linkedTo ? <Link size={14} className="text-indigo-500" /> : <User size={14} className="text-gray-500" />}
                  </div>
                  <div>
                    <p className="text-sm font-medium text-gray-900 dark:text-gray-100">{u.display_name}</p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">@{u.username}</p>
                    {linkedTo && (
                      <p className="text-xs text-indigo-500 dark:text-indigo-300">Linked to {linkedTo.display_name}'s data</p>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`badge-${u.role === "admin" ? "blue" : "amber"}`}>{u.role}</span>
                  <button
                    onClick={() => updateUserMut.mutate({ id: u.id, data: { is_active: !u.is_active } })}
                    className={`text-xs px-2 py-1 rounded-md ${u.is_active ? "text-green-600 bg-green-50 dark:bg-green-900/20" : "text-gray-400 bg-gray-100 dark:bg-gray-700"}`}
                  >
                    {u.is_active ? "Active" : "Inactive"}
                  </button>
                  <select
                    className="input text-xs w-auto py-1"
                    value={u.role}
                    onChange={e => updateUserMut.mutate({ id: u.id, data: { role: e.target.value } })}
                  >
                    <option value="admin">Admin</option>
                    <option value="viewer">View Only</option>
                  </select>
                  <button
                    onClick={() => { setResetPwUserId(u.id); setResetPwValue(""); setResetPwError(null); }}
                    className="btn-ghost p-1.5 text-amber-500 hover:bg-amber-50 dark:hover:bg-amber-900/20"
                    title="Reset password"
                  >
                    <RotateCcw size={14} />
                  </button>
                  {u.id !== me?.id && (
                    <button
                      onClick={() => removeUserMut.mutate(u.id)}
                      className="btn-ghost p-1.5 text-red-400 hover:bg-red-50"
                      title="Remove user"
                    >
                      <Trash2 size={14} />
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Activity Log ── */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100 flex items-center gap-2"><Activity size={16} className="text-indigo-500" /> Activity Log</h3>
          <div className="flex items-center gap-2">
            <select className="input text-xs w-auto py-1" value={logMethod} onChange={e => { setLogMethod(e.target.value); setLogPage(0); }}>
              <option value="">All methods</option>
              <option value="POST">POST</option>
              <option value="PATCH">PATCH</option>
              <option value="DELETE">DELETE</option>
            </select>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-100 dark:border-gray-700">
                <th className="text-left py-2 text-gray-500 font-medium pr-4">Time</th>
                <th className="text-left py-2 text-gray-500 font-medium pr-4">User</th>
                <th className="text-left py-2 text-gray-500 font-medium pr-4">Method</th>
                <th className="text-left py-2 text-gray-500 font-medium pr-4">Path</th>
                <th className="text-right py-2 text-gray-500 font-medium pr-4">Status</th>
                <th className="text-right py-2 text-gray-500 font-medium">ms</th>
              </tr>
            </thead>
            <tbody>
              {(logData?.items ?? []).map((log: any) => (
                <tr key={log.id} className="border-b border-gray-50 dark:border-gray-700/50 hover:bg-gray-50 dark:hover:bg-gray-700/30">
                  <td className="py-1.5 pr-4 text-gray-500 whitespace-nowrap">
                    {parseServerDateTime(log.timestamp).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                  </td>
                  <td className="py-1.5 pr-4 text-gray-700 dark:text-gray-300">{log.username ?? "—"}</td>
                  <td className="py-1.5 pr-4">
                    <span className={`badge-${log.method === "DELETE" ? "red" : log.method === "PATCH" ? "amber" : "blue"}`}>{log.method}</span>
                  </td>
                  <td className="py-1.5 pr-4 text-gray-600 dark:text-gray-400 font-mono">{log.path}</td>
                  <td className="py-1.5 pr-4 text-right">
                    <span className={log.status_code < 300 ? "text-green-600" : log.status_code < 500 ? "text-amber-600" : "text-red-600"}>{log.status_code}</span>
                  </td>
                  <td className="py-1.5 text-right text-gray-500">{log.duration_ms}</td>
                </tr>
              ))}
              {(!logData?.items?.length) && (
                <tr><td colSpan={6} className="text-center py-6 text-gray-400">No activity yet</td></tr>
              )}
            </tbody>
          </table>
        </div>
        {logData && logData.total > 25 && (
          <div className="flex items-center justify-between mt-3 text-xs text-gray-500">
            <span>{logData.total} total entries</span>
            <div className="flex gap-2">
              <button onClick={() => setLogPage(p => Math.max(0, p - 1))} disabled={logPage === 0} className="btn-ghost px-2 py-1 text-xs disabled:opacity-40">← Prev</button>
              <span className="self-center">Page {logPage + 1}</span>
              <button onClick={() => setLogPage(p => p + 1)} disabled={(logPage + 1) * 25 >= logData.total} className="btn-ghost px-2 py-1 text-xs disabled:opacity-40">Next →</button>
            </div>
          </div>
        )}
      </div>

      {/* ── Reset Password modal ── */}
      {resetPwUserId !== null && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-sm">
            <div className="flex justify-between items-center mb-5">
              <h3 className="font-bold text-gray-900 dark:text-gray-100">Reset Password</h3>
              <button onClick={() => { setResetPwUserId(null); setResetPwValue(""); setResetPwError(null); }} className="btn-ghost p-1"><X size={18} /></button>
            </div>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
              Set a new password for <strong>{users.find((u: any) => u.id === resetPwUserId)?.display_name ?? "this user"}</strong>. They will be able to change it again after logging in.
            </p>
            <div className="space-y-3">
              <div>
                <label className="label">New Password</label>
                <input
                  type="password"
                  className="input"
                  value={resetPwValue}
                  onChange={e => setResetPwValue(e.target.value)}
                  placeholder="At least 6 characters"
                  autoFocus
                />
              </div>
              {resetPwError && <p className="text-sm text-red-600">{resetPwError}</p>}
              <div className="flex gap-3 pt-2">
                <button
                  onClick={() => resetPwMut.mutate({ id: resetPwUserId, pw: resetPwValue })}
                  disabled={resetPwMut.isPending || resetPwValue.length < 6}
                  className="btn-primary flex-1"
                >
                  {resetPwMut.isPending ? "Saving…" : "Set Password"}
                </button>
                <button onClick={() => { setResetPwUserId(null); setResetPwValue(""); setResetPwError(null); }} className="btn-secondary flex-1">Cancel</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Add User modal ── */}
      {showUserForm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="card w-full max-w-sm">
            <div className="flex justify-between items-center mb-5">
              <h3 className="font-bold text-gray-900 dark:text-gray-100">Add User</h3>
              <button onClick={() => setShowUserForm(false)} className="btn-ghost p-1"><X size={18} /></button>
            </div>
            <form onSubmit={e => {
              e.preventDefault();
              createUserMut.mutate({
                ...userForm,
                linked_to_user_id: userForm.linked_to_user_id ? parseInt(userForm.linked_to_user_id) : null,
              });
            }} className="space-y-3">
              <div><label className="label">Display Name</label><input className="input" placeholder="Jane Ford" value={userForm.display_name} onChange={e => setUserForm({ ...userForm, display_name: e.target.value })} required /></div>
              <div><label className="label">Username</label><input className="input" placeholder="janeford" value={userForm.username} onChange={e => setUserForm({ ...userForm, username: e.target.value })} required /></div>
              <div><label className="label">Password</label><input type="password" className="input" value={userForm.password} onChange={e => setUserForm({ ...userForm, password: e.target.value })} required /></div>
              <div>
                <label className="label">Access Level</label>
                <select className="input" value={userForm.role} onChange={e => setUserForm({ ...userForm, role: e.target.value })}>
                  <option value="viewer">View Only</option>
                  <option value="admin">Admin</option>
                </select>
              </div>
              <div>
                <label className="label">Link to Account (shared data access)</label>
                <select className="input" value={userForm.linked_to_user_id} onChange={e => setUserForm({ ...userForm, linked_to_user_id: e.target.value })}>
                  <option value="">Own account (standalone)</option>
                  <option value={String(me?.id)}>Link to my account ({me?.display_name})</option>
                </select>
                <p className="text-xs text-gray-400 mt-1">Linked users see the same financial data as your account.</p>
              </div>
              <div className="flex gap-3 pt-2">
                <button type="submit" className="btn-primary flex-1">Create User</button>
                <button type="button" onClick={() => setShowUserForm(false)} className="btn-secondary flex-1">Cancel</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
