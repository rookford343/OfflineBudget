import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { authApi } from "../api";
import { DollarSign } from "lucide-react";

export default function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (newPassword !== confirm) {
      setError("Passwords don't match");
      return;
    }
    if (newPassword.length < 6) {
      setError("Password must be at least 6 characters");
      return;
    }
    setLoading(true);
    try {
      await authApi.resetPassword(token, newPassword);
      setSuccess(true);
    } catch (err: any) {
      setError(err.response?.data?.detail ?? "This reset link is invalid or has expired.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-indigo-50 to-white px-4">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-8">
          <div className="w-12 h-12 bg-indigo-600 rounded-xl flex items-center justify-center mb-3">
            <DollarSign className="text-white" size={24} />
          </div>
          <h1 className="text-2xl font-bold text-gray-900">Set a New Password</h1>
        </div>

        <div className="card">
          {success ? (
            <p className="text-sm text-green-700 bg-green-50 rounded-lg px-3 py-2">
              Password reset. <Link to="/login" className="underline">Sign in</Link>.
            </p>
          ) : (
            <form onSubmit={submit} className="space-y-4">
              <div>
                <label className="label">New Password</label>
                <input
                  type="password"
                  className="input"
                  autoComplete="new-password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                />
              </div>
              <div>
                <label className="label">Confirm Password</label>
                <input
                  type="password"
                  className="input"
                  autoComplete="new-password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  required
                />
              </div>
              {error && (
                <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>
              )}
              <button type="submit" className="btn-primary w-full" disabled={loading}>
                {loading ? "Please wait…" : "Reset Password"}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
