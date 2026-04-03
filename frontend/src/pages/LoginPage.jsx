import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import toast from "react-hot-toast";
import { Zap, Loader2 } from "lucide-react";

export default function LoginPage() {
  const [isRegister, setIsRegister] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("user");
  const [loading, setLoading] = useState(false);
  const { login, register } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      let user;
      if (isRegister) {
        user = await register(email, password, role);
        toast.success("Account created!");
      } else {
        user = await login(email, password);
        toast.success("Welcome back!");
      }
      navigate(user.role === "admin" ? "/admin/ingest" : "/chat");
    } catch (err) {
      toast.error(err.response?.data?.error?.message || "Authentication failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-50 px-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="mb-8 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-brand-600">
            <Zap className="h-6 w-6 text-white" />
          </div>
          <h1 className="text-xl font-bold text-surface-900">Schema Assistant</h1>
          <p className="mt-1 text-sm text-surface-400">
            AI-powered SQL schema analysis
          </p>
        </div>

        {/* Tabs */}
        <div className="mb-6 flex rounded-lg bg-surface-100 p-1">
          {["Login", "Register"].map((tab) => (
            <button
              key={tab}
              onClick={() => setIsRegister(tab === "Register")}
              className={`flex-1 rounded-md py-2 text-sm font-medium transition-colors ${
                (tab === "Register") === isRegister
                  ? "bg-white text-surface-800 shadow-sm"
                  : "text-surface-500 hover:text-surface-700"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="card p-6 space-y-4">
          <div>
            <label className="label">Email</label>
            <input
              type="email"
              className="input-field"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              required
            />
          </div>
          <div>
            <label className="label">Password</label>
            <input
              type="password"
              className="input-field"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              minLength={8}
              required
            />
          </div>
          {isRegister && (
            <div>
              <label className="label">Role</label>
              <select
                className="input-field"
                value={role}
                onChange={(e) => setRole(e.target.value)}
              >
                <option value="user">User</option>
                <option value="admin">Admin</option>
              </select>
              {role === "admin" && (
                <p className="mt-1 text-[11px] text-amber-600">
                  First admin is auto-approved. Subsequent admins require an existing admin.
                </p>
              )}
            </div>
          )}
          <button type="submit" disabled={loading} className="btn-primary w-full">
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : isRegister ? (
              "Create Account"
            ) : (
              "Sign In"
            )}
          </button>
        </form>
      </div>
    </div>
  );
}