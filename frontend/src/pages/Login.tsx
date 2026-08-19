import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { authApi } from "../api";
import { saveAuth } from "../store/auth";
import { DollarSign } from "lucide-react";

type Mode = "login" | "register";

export default function Login() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>("login");
  const [form, setForm] = useState({ username: "", password: "", display_name: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      let data: any;
      if (mode === "login") {
        data = await authApi.login(form.username, form.password);
      } else {
        data = await authApi.register(form.username, form.password, form.display_name || form.username);
      }
      saveAuth(data.access_token, data.user);
      navigate("/dashboard");
    } catch (err: any) {
      setError(err.response?.data?.detail ?? "Something went wrong.");
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
          <h1 className="text-2xl font-bold text-gray-900">OfflineBudget</h1>
          <p className="text-sm text-gray-500 mt-1">Your secure household budget</p>
        </div>

        <div className="card">
          <div className="flex rounded-lg bg-gray-100 p-1 mb-6">
            {(["login", "register"] as Mode[]).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`flex-1 py-1.5 text-sm font-medium rounded-md transition-colors ${
                  mode === m ? "bg-white dark:bg-[#3a4256] shadow-sm text-gray-900 dark:text-white" : "text-gray-500"
                }`}
              >
                {m === "login" ? "Sign In" : "Create Account"}
              </button>
            ))}
          </div>

          <form onSubmit={submit} className="space-y-4">
            {mode === "register" && (
              <div>
                <label className="label">Your Name</label>
                <input
                  className="input"
                  placeholder="Alex Smith"
                  value={form.display_name}
                  onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                />
              </div>
            )}
            <div>
              <label className="label">Username</label>
              <input
                className="input"
                placeholder="username"
                autoComplete="username"
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
                required
              />
            </div>
            <div>
              <label className="label">Password</label>
              <input
                type="password"
                className="input"
                placeholder="••••••••"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                required
              />
            </div>
            {mode === "login" && (
              <div className="text-right -mt-2">
                <Link to="/forgot-password" className="text-xs text-indigo-600 hover:underline">
                  Forgot password?
                </Link>
              </div>
            )}
            {error && (
              <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>
            )}
            <button type="submit" className="btn-primary w-full" disabled={loading}>
              {loading ? "Please wait…" : mode === "login" ? "Sign In" : "Create Account"}
            </button>
          </form>
        </div>
        <p className="text-center text-xs text-gray-400 mt-6">
          Runs locally — your data never leaves your home network
        </p>
      </div>
    </div>
  );
}
