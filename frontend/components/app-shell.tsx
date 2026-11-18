"use client";
import {
  BarChart3, Bell, Bot, CalendarClock, Film, LayoutDashboard, Loader2, LogOut, Moon, Pause, Play, Settings, Sparkles,
  TrendingUp, Tv,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Badge, Button, cn } from "@/components/ui";
import { useAction, useApi, useMe } from "@/hooks/use-api";
import { api } from "@/services/api";
import type { Notification } from "@/types";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/trends", label: "Trend Discovery", icon: TrendingUp },
  { href: "/studio", label: "Content Studio", icon: Sparkles },
  { href: "/library", label: "Video Library", icon: Film },
  { href: "/scheduler", label: "Scheduler & Approvals", icon: CalendarClock },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/channels", label: "Channels", icon: Tv },
  { href: "/ai", label: "AI Configuration", icon: Bot },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const me = useMe();
  const router = useRouter();
  const path = usePathname();
  const [bellOpen, setBellOpen] = useState(false);
  const status = useApi<{ running: boolean; paused_reason: string | null }>(me.data ? "/automation/status" : null, { refetchInterval: 15_000 });
  const notes = useApi<Notification[]>(me.data ? "/notifications" : null, { refetchInterval: 20_000 });
  const toggle = useAction((run: boolean) => api.post(run ? "/automation/resume" : "/automation/pause"), ["/automation", "/dashboard"]);
  const markRead = useAction(() => api.post("/notifications/read"), ["/notifications"]);

  useEffect(() => {
    if (me.isError) router.replace("/login");
    else if (me.data && !me.data.onboarding_completed && me.data.role === "admin") router.replace("/onboarding");
  }, [me.isError, me.data, router]);

  useEffect(() => {
    try {
      if (localStorage.getItem("theme") === "dark") document.documentElement.classList.add("dark");
    } catch { /* storage unavailable */ }
  }, []);

  if (!me.data) {
    return <div className="flex h-screen items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-primary" /></div>;
  }
  const unread = (notes.data ?? []).filter((n) => !n.read).length;
  const running = status.data?.running;

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-border bg-card md:flex">
        <div className="flex items-center gap-2 px-5 py-5 font-semibold"><Sparkles className="h-5 w-5 text-primary" /> AI YouTube Studio</div>
        <nav className="flex-1 space-y-0.5 px-3">
          {NAV.map(({ href, label, icon: Icon }) => (
            <Link key={href} href={href}
              className={cn("flex items-center gap-2 rounded-md px-3 py-2 text-sm", path.startsWith(href) ? "bg-primary/10 font-medium text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground")}>
              <Icon className="h-4 w-4" /> {label}
            </Link>
          ))}
        </nav>
        <div className="border-t border-border p-3 text-xs text-muted-foreground">
          <div className="truncate">{me.data.email}</div>
          <div className="mt-2 flex gap-1">
            <Button variant="ghost" size="sm" aria-label="Toggle dark mode" onClick={() => {
              const dark = document.documentElement.classList.toggle("dark");
              try { localStorage.setItem("theme", dark ? "dark" : "light"); } catch { /* ignore */ }
            }}><Moon className="h-4 w-4" /></Button>
            <Button variant="ghost" size="sm" onClick={async () => { await api.post("/auth/logout"); router.replace("/login"); }}>
              <LogOut className="h-4 w-4" /> Sign out
            </Button>
          </div>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-border bg-background/90 px-4 py-3 backdrop-blur md:px-8">
          <select className="rounded-md border border-border bg-card px-2 py-1 text-sm md:hidden" value={NAV.find((n) => path.startsWith(n.href))?.href}
            onChange={(e) => router.push(e.target.value)}>
            {NAV.map((n) => <option key={n.href} value={n.href}>{n.label}</option>)}
          </select>
          <div className="flex items-center gap-2 text-sm">
            <span className={cn("h-2 w-2 rounded-full", running ? "bg-emerald-500" : "bg-amber-500")} />
            {running ? "Automation running" : "Automation paused"}
            {status.data?.paused_reason && <Badge tone="red">{status.data.paused_reason}</Badge>}
          </div>
          <div className="relative flex items-center gap-2">
            {me.data.role !== "viewer" && (
              <Button size="sm" variant={running ? "outline" : "default"} loading={toggle.isPending} onClick={() => toggle.mutate(!running)}>
                {running ? <><Pause className="h-4 w-4" /> Pause all</> : <><Play className="h-4 w-4" /> Start automation</>}
              </Button>
            )}
            <Button variant="ghost" size="icon" aria-label="Notifications" onClick={() => setBellOpen(!bellOpen)}>
              <Bell className="h-4 w-4" />
              {unread > 0 && <span className="absolute -mt-4 ml-4 rounded-full bg-red-500 px-1 text-[10px] text-white">{unread}</span>}
            </Button>
            {bellOpen && (
              <div className="absolute right-0 top-11 w-80 rounded-lg border border-border bg-card p-2 shadow-xl">
                <div className="flex items-center justify-between px-2 py-1 text-sm font-medium">
                  Notifications
                  <button className="text-xs text-primary" onClick={() => markRead.mutate(undefined)}>Mark all read</button>
                </div>
                <div className="max-h-96 overflow-auto">
                  {(notes.data ?? []).slice(0, 30).map((n) => (
                    <Link key={n.id} href={n.link ?? "#"} onClick={() => setBellOpen(false)}
                      className={cn("block rounded px-2 py-2 text-sm hover:bg-muted", !n.read && "bg-primary/5")}>
                      <div className="flex items-center gap-2">
                        {n.level !== "info" && <Badge tone={n.level === "critical" ? "red" : "amber"}>{n.level}</Badge>}
                        <span className="font-medium">{n.title}</span>
                      </div>
                      <div className="line-clamp-2 text-xs text-muted-foreground">{n.message}</div>
                    </Link>
                  ))}
                  {!notes.data?.length && <p className="p-3 text-sm text-muted-foreground">No notifications yet.</p>}
                </div>
              </div>
            )}
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 p-4 md:p-8">{children}</main>
      </div>
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
