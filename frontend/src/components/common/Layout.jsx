import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import {
  Database,
  GitBranch,
  MessageSquare,
  LogOut,
  Shield,
  Settings,
  Zap,
} from "lucide-react";

const NAV_ADMIN = [
  { to: "/admin/ingest", label: "Schema Ingestion", icon: Database },
  { to: "/admin/workflows", label: "Workflows", icon: GitBranch },
];

const NAV_USER = [
  { to: "/chat", label: "Chat", icon: MessageSquare },
];

export default function Layout() {
  const { user, logout, isAdmin } = useAuth();
  const navigate = useNavigate();
  const navItems = isAdmin ? [...NAV_ADMIN, ...NAV_USER] : NAV_USER;

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="flex w-60 flex-col border-r border-surface-200 bg-white">
        {/* Logo */}
        <div className="flex items-center gap-2.5 border-b border-surface-100 px-5 py-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600">
            <Zap className="h-4 w-4 text-white" />
          </div>
          <span className="text-sm font-semibold text-surface-800">
            Schema Assistant
          </span>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto px-3 py-4">
          {isAdmin && (
            <p className="mb-2 px-2 text-[11px] font-semibold uppercase tracking-wider text-surface-400">
              Admin
            </p>
          )}
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? "bg-brand-50 font-medium text-brand-700"
                    : "text-surface-600 hover:bg-surface-50 hover:text-surface-800"
                }`
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* User footer */}
        <div className="border-t border-surface-100 p-3">
          <div className="flex items-center gap-2.5 rounded-lg px-2 py-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-surface-100 text-xs font-medium text-surface-600">
              {(user?.display_name || user?.email || "?")[0].toUpperCase()}
            </div>
            <div className="flex-1 min-w-0">
              <p className="truncate text-sm font-medium text-surface-800">
                {user?.display_name || user?.email}
              </p>
              <p className="flex items-center gap-1 text-[11px] text-surface-400">
                {isAdmin && <Shield className="h-3 w-3" />}
                {user?.role}
              </p>
            </div>
            <button
              onClick={handleLogout}
              className="rounded-md p-1.5 text-surface-400 hover:bg-surface-100 hover:text-surface-600 transition-colors"
              title="Logout"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto bg-surface-50">
        <Outlet />
      </main>
    </div>
  );
}