"use client";
import { ChevronLeft, ChevronRight, RotateCcw, X } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { PageHeader } from "@/components/app-shell";
import { PublishDialog } from "@/components/publish-dialog";
import { Badge, Button, Card, CardTitle, Empty, StatusBadge, cn } from "@/components/ui";
import { useAction, useApi } from "@/hooks/use-api";
import { api } from "@/services/api";
import type { Approval, Video } from "@/types";

interface Job { id: number; video_id: number; title: string; status: string; privacy_status: string; scheduled_for: string | null;
  attempts: number; last_error: string | null; youtube_video_id: string | null; created_at: string; bytes_uploaded: number }

export default function Scheduler() {
  const approvals = useApi<Approval[]>("/approvals", { refetchInterval: 15_000 });
  const jobs = useApi<Job[]>("/publishing/jobs", { refetchInterval: 10_000 });
  const videos = useApi<Video[]>("/videos?status=published,scheduled,uploaded");
  const retry = useAction((id: number) => api.post(`/publishing/jobs/${id}/retry`), ["/publishing"]);
  const cancel = useAction((id: number) => api.post(`/publishing/jobs/${id}/cancel`), ["/publishing"]);
  const [deciding, setDeciding] = useState<Approval | null>(null);

  return (
    <>
      <PageHeader title="Scheduler & Approvals" description="Approve videos, see what goes out when, and retry failed uploads." />
      <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
        <Calendar jobs={jobs.data ?? []} videos={videos.data ?? []} />
        <Card>
          <CardTitle>Waiting for you ({approvals.data?.length ?? 0})</CardTitle>
          <div className="mt-3 space-y-2">
            {!approvals.data?.length && <p className="text-sm text-muted-foreground">Nothing to approve.</p>}
            {approvals.data?.map((a) => (
              <div key={a.id} className="rounded-md border border-border p-3 text-sm">
                <div className="flex items-center gap-2"><Badge tone="amber">{a.kind === "script" ? "script" : "video"}</Badge><span className="line-clamp-1 font-medium">{a.summary}</span></div>
                <div className="mt-2 flex gap-2">
                  {a.run_id && <Link href={`/studio?run=${a.run_id}`}><Button size="sm" variant="outline">Open in studio</Button></Link>}
                  {a.kind === "video_publish" && <Button size="sm" variant="success" onClick={() => setDeciding(a)}>Decide…</Button>}
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
      <Card className="mt-4">
        <CardTitle>Upload jobs</CardTitle>
        {!jobs.data?.length ? <Empty title="No uploads yet" /> : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground"><tr><th className="py-2">Video</th><th>Status</th><th>Privacy</th><th>Release</th><th>Attempts</th><th /></tr></thead>
              <tbody>
                {jobs.data.map((j) => (
                  <tr key={j.id} className="border-t border-border">
                    <td className="py-2 pr-2">{j.title}{j.last_error && <div className="text-xs text-red-600">{j.last_error}</div>}</td>
                    <td><StatusBadge status={j.status} /></td>
                    <td>{j.privacy_status}</td>
                    <td>{j.scheduled_for ? new Date(j.scheduled_for).toLocaleString() : "immediately"}</td>
                    <td>{j.attempts}</td>
                    <td className="space-x-1 text-right">
                      {["failed", "queued"].includes(j.status) && <Button size="sm" variant="outline" onClick={() => retry.mutate(j.id)}><RotateCcw className="h-3 w-3" /> Retry</Button>}
                      {["failed", "queued"].includes(j.status) && <Button size="sm" variant="ghost" onClick={() => cancel.mutate(j.id)}><X className="h-3 w-3" /></Button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {deciding && <PublishDialog approvalId={deciding.id} suggested={deciding.payload.suggested_slot} onClose={() => setDeciding(null)} />}
    </>
  );
}

function Calendar({ jobs, videos }: { jobs: Job[]; videos: Video[] }) {
  const [offset, setOffset] = useState(0);
  const start = useMemo(() => {
    const d = new Date();
    d.setDate(1);
    d.setMonth(d.getMonth() + offset);
    d.setHours(0, 0, 0, 0);
    return d;
  }, [offset]);
  const days: Date[] = [];
  const first = new Date(start);
  first.setDate(1 - ((start.getDay() + 6) % 7));
  for (let i = 0; i < 42; i++) days.push(new Date(first.getFullYear(), first.getMonth(), first.getDate() + i));
  const events = [
    ...jobs.filter((j) => j.status !== "cancelled").map((j) => ({ date: new Date(j.scheduled_for ?? j.created_at), title: j.title, status: j.status })),
    ...videos.filter((v) => v.published_at && !jobs.some((j) => j.video_id === v.id)).map((v) => ({ date: new Date(v.published_at!), title: v.metadata?.title ?? "", status: v.status })),
  ];
  const today = new Date().toDateString();
  return (
    <Card>
      <div className="flex items-center justify-between">
        <CardTitle>{start.toLocaleString(undefined, { month: "long", year: "numeric" })}</CardTitle>
        <div className="flex gap-1">
          <Button size="icon" variant="ghost" aria-label="previous month" onClick={() => setOffset(offset - 1)}><ChevronLeft className="h-4 w-4" /></Button>
          <Button size="icon" variant="ghost" aria-label="next month" onClick={() => setOffset(offset + 1)}><ChevronRight className="h-4 w-4" /></Button>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-7 gap-1 text-xs">
        {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => <div key={d} className="pb-1 text-center text-muted-foreground">{d}</div>)}
        {days.map((d) => {
          const evs = events.filter((e) => e.date.toDateString() === d.toDateString());
          return (
            <div key={d.toISOString()} className={cn("min-h-20 rounded border border-border p-1", d.getMonth() !== start.getMonth() && "opacity-40",
              d.toDateString() === today && "border-primary")}>
              <div className="text-right text-[10px]">{d.getDate()}</div>
              {evs.slice(0, 3).map((e, i) => (
                <div key={i} title={e.title} className={cn("mt-0.5 truncate rounded px-1 text-[10px]",
                  e.status === "failed" ? "bg-red-100 text-red-800" : e.status === "succeeded" ? "bg-emerald-100 text-emerald-800" : "bg-blue-100 text-blue-800")}>
                  {e.date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} {e.title}
                </div>
              ))}
              {evs.length > 3 && <div className="text-[10px] text-muted-foreground">+{evs.length - 3} more</div>}
            </div>
          );
        })}
      </div>
    </Card>
  );
}
