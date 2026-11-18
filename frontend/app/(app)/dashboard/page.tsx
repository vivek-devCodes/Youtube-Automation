"use client";
import { AlertTriangle, CheckCircle2, Clock, DollarSign, Eye, Film, Users, Youtube } from "lucide-react";
import Link from "next/link";
import { PageHeader } from "@/components/app-shell";
import { Badge, Button, Card, CardTitle, Progress, Stat } from "@/components/ui";
import { useApi } from "@/hooks/use-api";

interface Dash {
  channels: number; sandbox_channels: number; videos_generated: number; videos_published: number; shorts_published: number;
  long_published: number; total_views: number; total_subscribers: number; estimated_revenue: number | null;
  pending_approvals: number; active_runs: number; failed_runs_7d: number;
  automation: { running: boolean; paused_reason: string | null; budget_mode: string; last_trend_scan_at: string | null };
  costs: { month_to_date: number; monthly_budget: number; youtube_quota_used_today: number; youtube_quota_limit: number };
  ypp: { targets: { early_access: Record<string, number>; full: Record<string, number> };
    progress: Record<string, number>; note: string };
  worker: { ok: boolean; mode: string; current?: string | null };
}

const fmt = (n: number) => Intl.NumberFormat("en", { notation: "compact" }).format(n);

export default function Dashboard() {
  const { data: d } = useApi<Dash>("/dashboard", { refetchInterval: 15_000 });
  if (!d) return <PageHeader title="Dashboard" />;
  const full = d.ypp.targets.full;
  const early = d.ypp.targets.early_access;
  const p = d.ypp.progress;
  return (
    <>
      <PageHeader title="Dashboard" description="Your content factory at a glance."
        actions={<Link href="/trends"><Button>Find a topic</Button></Link>} />
      {d.sandbox_channels > 0 && d.sandbox_channels === d.channels && (
        <p className="mb-4 rounded-md bg-amber-50 p-3 text-sm text-amber-800 dark:bg-amber-900/30 dark:text-amber-200">
          You are using a <b>sandbox</b> channel: uploads and analytics are simulated locally. Connect a real channel on the Channels page when you&apos;re ready.
        </p>
      )}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Channels" value={d.channels} icon={<Youtube className="h-4 w-4" />} />
        <Stat label="Videos generated" value={d.videos_generated} icon={<Film className="h-4 w-4" />} />
        <Stat label="Published" value={d.videos_published} hint={`${d.shorts_published} Shorts · ${d.long_published} long-form`} icon={<CheckCircle2 className="h-4 w-4" />} />
        <Stat label="Pending approvals" value={<Link href="/scheduler" className="text-primary">{d.pending_approvals}</Link>} icon={<Clock className="h-4 w-4" />} />
        <Stat label="Total views" value={fmt(d.total_views)} icon={<Eye className="h-4 w-4" />} />
        <Stat label="Subscribers" value={fmt(d.total_subscribers)} hint="real channels only" icon={<Users className="h-4 w-4" />} />
        <Stat label="Estimated revenue" value={d.estimated_revenue == null ? "—" : `$${d.estimated_revenue}`} hint="needs monetary analytics scope" icon={<DollarSign className="h-4 w-4" />} />
        <Stat label="AI costs this month" value={`$${d.costs.month_to_date.toFixed(2)}`} hint={d.automation.budget_mode === "free" ? "free mode" : `of $${d.costs.monthly_budget}`} />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <Card>
          <CardTitle>Automation</CardTitle>
          <div className="mt-3 space-y-2 text-sm">
            <div className="flex justify-between"><span>Status</span><Badge tone={d.automation.running ? "green" : "amber"}>{d.automation.running ? "running" : "paused"}</Badge></div>
            {d.automation.paused_reason && <p className="flex gap-1 text-red-600"><AlertTriangle className="h-4 w-4" /> {d.automation.paused_reason}</p>}
            <div className="flex justify-between"><span>Active productions</span><span>{d.active_runs}</span></div>
            <div className="flex justify-between"><span>Failed (7 days)</span><span className={d.failed_runs_7d ? "text-red-600" : ""}>{d.failed_runs_7d}</span></div>
            <div className="flex justify-between"><span>Last trend scan</span><span>{d.automation.last_trend_scan_at ? new Date(d.automation.last_trend_scan_at).toLocaleString() : "never"}</span></div>
            <div className="flex justify-between"><span>Worker ({d.worker.mode})</span><Badge tone={d.worker.ok ? "green" : "red"}>{d.worker.ok ? "healthy" : "down"}</Badge></div>
            {d.worker.current && <p className="truncate text-xs text-muted-foreground">Working on: {d.worker.current}</p>}
          </div>
        </Card>
        <Card>
          <CardTitle>API usage</CardTitle>
          <div className="mt-3 space-y-3 text-sm">
            <div>
              <div className="flex justify-between"><span>AI budget</span><span>${d.costs.month_to_date.toFixed(2)} / ${d.costs.monthly_budget}</span></div>
              <Progress value={d.costs.monthly_budget ? (100 * d.costs.month_to_date) / d.costs.monthly_budget : 0} className="mt-1" />
            </div>
            <div>
              <div className="flex justify-between"><span>YouTube quota today</span><span>{d.costs.youtube_quota_used_today} / {d.costs.youtube_quota_limit}</span></div>
              <Progress value={(100 * d.costs.youtube_quota_used_today) / d.costs.youtube_quota_limit} className="mt-1" />
            </div>
          </div>
        </Card>
        <Card>
          <CardTitle>YouTube Partner Program progress</CardTitle>
          <div className="mt-3 space-y-2 text-sm">
            <Goal label="Subscribers" value={p.subscribers} target={full.subscribers} early={early.subscribers} />
            <Goal label="Long-form watch hours (12 mo)" value={p.watch_hours_12m} target={full.watch_hours_12m} early={early.watch_hours_12m} />
            <Goal label="Shorts views (90 days)" value={p.shorts_views_90d} target={full.shorts_views_90d} early={early.shorts_views_90d} />
            <Goal label="Public uploads (90 days)" value={p.public_uploads_90d} target={early.public_uploads_90d} />
            <p className="text-xs text-muted-foreground">{d.ypp.note} Either the watch-hours or the Shorts-views path qualifies.</p>
          </div>
        </Card>
      </div>
    </>
  );
}

function Goal({ label, value, target, early }: { label: string; value: number; target: number; early?: number }) {
  return (
    <div>
      <div className="flex justify-between"><span>{label}</span><span>{fmt(value)} / {fmt(target)}{early ? ` (early: ${fmt(early)})` : ""}</span></div>
      <Progress value={(100 * value) / target} className="mt-1" />
    </div>
  );
}
