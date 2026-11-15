import { useQuery } from "@tanstack/react-query";
import { LayoutDashboard, LogOut, Map, Menu, MessagesSquare, PlusCircle, Settings, UserRound, Users, X } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { Logo } from "../components/Logo";
import { Avatar } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/Toast";
import { api } from "../lib/api";
import type { TripSummary } from "../lib/types";

export default function AppShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const loc = useLocation();
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [loc.pathname]);

  const trips = useQuery({ queryKey: ["trips"], queryFn: () => api<TripSummary[]>("/api/trips") });
  const hasTrips = (trips.data?.length ?? 0) > 0;

  const items = [
    { to: "/app", label: "Overview", icon: LayoutDashboard, end: true },
    { to: "/app/trips", label: "My Trips", icon: Map, end: true },
    { to: "/app/trips/new", label: "Create a Trip", icon: PlusCircle },
    { to: "/app/join", label: "Join a Trip", icon: Users },
    ...(hasTrips ? [{ to: "/app/chat", label: "Group Chat", icon: MessagesSquare }] : []),
    { to: "/app/profile", label: "Profile", icon: UserRound },
    { to: "/app/settings", label: "Settings", icon: Settings },
  ];

  const doLogout = async () => {
    try { await logout(); navigate("/", { replace: true }); }
    catch { toast.error("Couldn’t log out. Please try again."); }
  };

  const nav = (
    <nav aria-label="Main" className="flex h-full flex-col">
      <div className="px-5 py-5"><Logo to="/app" /></div>
      <ul className="flex-1 space-y-1 px-3">
        {items.map(({ to, label, icon: Icon, end }) => (
          <li key={to}>
            <NavLink to={to} end={end}
              className={({ isActive }) => `flex items-center gap-3 rounded-xl px-3 py-2.5 text-[15px] font-medium transition-colors ${isActive ? "bg-lagoon-50 text-lagoon-800" : "text-ink-700 hover:bg-sand-100"}`}>
              <Icon className="h-[18px] w-[18px]" aria-hidden />{label}
            </NavLink>
          </li>
        ))}
      </ul>
      <div className="border-t border-sand-200 p-3">
        <div className="mb-2 flex items-center gap-3 px-2 py-1.5">
          <Avatar name={user!.name} />
          <div className="min-w-0"><p className="truncate text-sm font-semibold">{user!.name}</p><p className="truncate text-xs text-ink-500">{user!.email}</p></div>
        </div>
        <button onClick={doLogout} className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-[15px] font-medium text-ink-700 hover:bg-sand-100">
          <LogOut className="h-[18px] w-[18px]" aria-hidden />Log out
        </button>
      </div>
    </nav>
  );

  return (
    <div className="min-h-screen lg:flex">
      <aside className="no-print sticky top-0 hidden h-screen w-64 shrink-0 border-r border-sand-200 bg-white lg:block">{nav}</aside>

      <header className="no-print sticky top-0 z-30 flex items-center justify-between border-b border-sand-200 bg-white/90 px-4 py-3 backdrop-blur lg:hidden">
        <Logo to="/app" />
        <button className="btn-ghost !p-2" aria-label="Open menu" aria-expanded={open} onClick={() => setOpen(true)}><Menu className="h-6 w-6" /></button>
      </header>
      {open && (
        <div className="no-print fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <div className="absolute inset-0 bg-ink-950/40" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-72 max-w-[85%] bg-white shadow-xl">
            <button className="btn-ghost absolute right-2 top-3 !p-2" aria-label="Close menu" onClick={() => setOpen(false)}><X className="h-5 w-5" /></button>
            {nav}
          </div>
        </div>
      )}

      <main className="min-w-0 flex-1">
        <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:py-8"><Outlet /></div>
      </main>
    </div>
  );
}

