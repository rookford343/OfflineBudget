import { useState } from "react";
import { Link } from "react-router-dom";
import { authApi } from "../api";
import { DollarSign } from "lucide-react";

export default function ForgotPassword() {
  const [username, setUsername] = useState("");
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [codeError, setCodeError] = useState("");
  const [codeSuccess, setCodeSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  async function submitUsername(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      await authApi.forgotPassword(username);
    } finally {
      setLoading(false);
      setSubmitted(true);
    }
  }

  async function submitCode(e: React.FormEvent) {
    e.preventDefault();
    setCodeError("");
    if (newPassword.length < 6) {
      setCodeError("Password must be at least 6 characters");
      return;
    }
    setLoading(true);
    try {
      await authApi.resetPasswordWithCode(username, code, newPassword);
      setCodeSuccess(true);
    } catch (err: any) {
      setCodeError(err.response?.data?.detail ?? "Invalid recovery code");
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
          <h1 className="text-2xl font-bold text-gray-900">Reset Your Password</h1>
        </div>

        <div className="card space-y-6">
          {codeSuccess ? (
            <p className="text-sm text-green-700 bg-green-50 rounded-lg px-3 py-2">
              Password reset. <Link to="/login" className="underline">Sign in</Link>.
            </p>
          ) : (
            <>
              {!submitted ? (
                <form onSubmit={submitUsername} className="space-y-4">
                  <div>
                    <label className="label">Username</label>
                    <input
                      className="input"
                      autoComplete="username"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      required
                    />
                  </div>
                  <button type="submit" className="btn-primary w-full" disabled={loading}>
                    {loading ? "Please wait…" : "Send Reset Link"}
                  </button>
                </form>
              ) : (
                <p className="text-sm text-gray-600 bg-gray-50 rounded-lg px-3 py-2">
                  If that account has an email on file, a reset link is on its way.
                </p>
              )}

              <div className="border-t pt-4">
                <p className="text-sm text-gray-500 mb-3">Have a recovery code instead?</p>
                <form onSubmit={submitCode} className="space-y-3">
                  <input
                    className="input"
                    placeholder="Username"
                    autoComplete="username"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    required
                  />
                  <input
                    className="input"
                    placeholder="Recovery code"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    required
                  />
                  <input
                    type="password"
                    className="input"
                    placeholder="New password"
                    autoComplete="new-password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    required
                  />
                  {codeError && (
                    <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{codeError}</p>
                  )}
                  <button type="submit" className="btn-primary w-full" disabled={loading}>
                    {loading ? "Please wait…" : "Reset with Code"}
                  </button>
                </form>
              </div>
            </>
          )}
        </div>
        <p className="text-center text-xs text-gray-400 mt-6">
          <Link to="/login" className="underline">Back to sign in</Link>
        </p>
      </div>
    </div>
  );
}
