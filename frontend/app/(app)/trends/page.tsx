"use client";
import { ExternalLink, Lightbulb, RefreshCw, ThumbsDown, ThumbsUp } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { PageHeader } from "@/components/app-shell";
import { Badge, Button, Card, Dialog, Empty, ErrorText, Field, Input, Select, StatusBadge, Switch } from "@/components/ui";
import { useAction, useApi } from "@/hooks/use-api";
import { api } from "@/services/api";
import type { Channel, Trend } from "@/types";

export default function TrendsPage() {
  const router = useRouter();
  const channels = useApi<Channel[]>("/channels");
  const [channelId, setChannelId] = useState<number | "">("");
  const [status, setStatus] = useState("new");
  const [source, setSource] = useState("");
  const cid = channelId || channels.data?.[0]?.id;
  const trends = useApi<Trend[]>(cid ? `/trends?channel_id=${cid}&status=${status}${source ? `&source=${source}` : ""}` : null, { refetchInterval: 20_000 });
  const scan = useAction(() => api.post("/trends/scan", { channel_id: cid }), ["/trends"]);
  const reject = useAction((id: number) => api.post(`/trends/${id}/reject`), ["/trends"]);
  const ideas = useAction((id: number) => api.post(`/trends/${id}/ideas`), ["/trends"]);
  const [approving, setApproving] = useState<Trend | null>(null);
  const [manual, setManual] = useState(false);

  return (
    <>
      <PageHeader title="Trend Discovery" description="Trending topics are research inputs only — every video is written and produced from scratch."
        actions={<>
          <Button variant="outline" onClick={() => setManual(true)}><Lightbulb className="h-4 w-4" /> Own topic</Button>
          <Button loading={scan.isPending} onClick={() => scan.mutate(undefined)}><RefreshCw className="h-4 w-4" /> Scan now</Button>
        </>} />
      {scan.isSuccess && <p className="mb-3 text-sm text-muted-foreground">Scan queued — results appear here in a minute.</p>}
      <div className="mb-4 flex flex-wrap gap-2">
        <Select className="w-56" value={cid ?? ""} onChange={(e) => setChannelId(Number(e.target.value))}>
          {channels.data?.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
        </Select>
        <Select className="w-40" value={status} onChange={(e) => setStatus(e.target.value)}>
          {["new", "approved", "used", "rejected"].map((s) => <option key={s} value={s}>{s}</option>)}
        </Select>
        <Select className="w-44" value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="">All sources</option>
          {["youtube", "google_trends", "news", "mock", "manual"].map((s) => <option key={s} value={s}>{s}</option>)}
        </Select>
      </div>
      {!trends.data?.length ? (
        <Empty title="No trends yet">Click “Scan now”. Without a YouTube API key, discovery uses Google Trends, news feeds and evergreen topics.</Empty>
      ) : (
        <div className="space-y-3">
          {trends.data.map((t) => (
            <Card key={t.id} className="p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <ScoreBadge score={t.score} />
                    <span className="font-medium">{t.topic}</span>
                    <Badge>{t.source}</Badge>
                    {t.niche && <Badge tone="violet">{t.niche}</Badge>}
                    <StatusBadge status={t.status} />
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-4 text-xs text-muted-foreground">
                    {t.source_channel && <span>{t.source_channel}</span>}
                    {t.region && <span>{t.region}{t.language ? ` · ${t.language}` : ""}</span>}
                    <span>{Intl.NumberFormat("en", { notation: "compact" }).format(t.view_count)} {t.source === "google_trends" ? "searches" : "views"}</span>
                    {t.view_velocity > 0 && <span>{Intl.NumberFormat("en", { notation: "compact" }).format(t.view_velocity)}/hour</span>}
                    <span>competition {(t.competition * 100).toFixed(0)}%</span>
                    {t.source_url && <a className="inline-flex items-center gap-1 text-primary" href={t.source_url} target="_blank" rel="noreferrer">reference <ExternalLink className="h-3 w-3" /></a>}
                  </div>
                  <Breakdown b={t.score_breakdown} />
                  {typeof t.score_breakdown.why_it_works === "string" && <p className="mt-2 text-sm"><b>Why it works:</b> {t.score_breakdown.why_it_works}</p>}
                  {t.suggested_ideas.length > 0 && (
                    <ul className="mt-2 list-disc pl-5 text-sm">{t.suggested_ideas.map((i) => <li key={i}>{i}</li>)}</ul>
                  )}
                </div>
                {t.status === "new" && (
                  <div className="flex flex-wrap gap-2">
                    {!t.suggested_ideas.length && <Button size="sm" variant="outline" loading={ideas.isPending && ideas.variables === t.id} onClick={() => ideas.mutate(t.id)}>Suggest ideas</Button>}
                    <Button size="sm" variant="outline" onClick={() => reject.mutate(t.id)}><ThumbsDown className="h-4 w-4" /> Reject</Button>
                    <Button size="sm" onClick={() => setApproving(t)}><ThumbsUp className="h-4 w-4" /> Approve</Button>
                  </div>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
      {approving && <ApproveDialog trend={approving} onClose={() => setApproving(null)} onDone={(run) => router.push(`/studio?run=${run}`)} />}
      {manual && cid && <ManualDialog channelId={cid} onClose={() => setManual(false)} onDone={(run) => router.push(`/studio?run=${run}`)} />}
    </>
  );
}

function ScoreBadge({ score }: { score: number }) {
  const tone = score >= 70 ? "green" : score >= 50 ? "amber" : "gray";
  return <Badge tone={tone} className="tabular-nums">{score.toFixed(0)}</Badge>;
}

function Breakdown({ b }: { b: Trend["score_breakdown"] }) {
  const keys = ["view_velocity", "engagement", "search_interest", "freshness", "relevance", "feasibility"];
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {keys.filter((k) => typeof b[k] === "number").map((k) => (
        <span key={k} className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">{k.replace("_", " ")} {Math.round((b[k] as number) * 100)}</span>
      ))}
    </div>
  );
}

function ApproveDialog({ trend, onClose, onDone }: { trend: Trend; onClose: () => void; onDone: (run: number) => void }) {
  const [format, setFormat] = useState("short");
  const [title, setTitle] = useState(trend.suggested_ideas[0] ?? trend.topic);
  const [review, setReview] = useState(true);
  const approve = useAction(() => api.post<{ run_id: number }>(`/trends/${trend.id}/approve`, { format, title, start_production: true, review_script: review }), ["/trends", "/content"]);
  return (
    <Dialog open onClose={onClose} title="Produce an original video">
      <div className="space-y-3">
        <Field label="Working title"><Input value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
        {trend.suggested_ideas.length > 1 && (
          <div className="flex flex-wrap gap-1">{trend.suggested_ideas.map((i) => <button key={i} className="rounded bg-muted px-2 py-1 text-xs" onClick={() => setTitle(i)}>{i}</button>)}</div>
        )}
        <Field label="Format">
          <Select value={format} onChange={(e) => setFormat(e.target.value)}>
            <option value="short">Short (9:16)</option>
            <option value="long">Long-form (16:9)</option>
          </Select>
        </Field>
        <Switch checked={review} onChange={setReview} label="Let me review/edit the script before rendering" />
        <ErrorText error={approve.error} />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button loading={approve.isPending} onClick={() => approve.mutate(undefined, { onSuccess: (r) => onDone(r.run_id) })}>Start production</Button>
        </div>
      </div>
    </Dialog>
  );
}

function ManualDialog({ channelId, onClose, onDone }: { channelId: number; onClose: () => void; onDone: (run: number) => void }) {
  const [topic, setTopic] = useState("");
  const [format, setFormat] = useState("short");
  const gen = useAction(() => api.post<{ run_id: number }>("/content/generate", { channel_id: channelId, topic, format, review_script: true }), ["/content"]);
  return (
    <Dialog open onClose={onClose} title="Create a video about your own topic">
      <div className="space-y-3">
        <Field label="Topic" hint="Be specific, e.g. 'Why the Moon is drifting away from Earth'"><Input value={topic} onChange={(e) => setTopic(e.target.value)} /></Field>
        <Field label="Format">
          <Select value={format} onChange={(e) => setFormat(e.target.value)}><option value="short">Short</option><option value="long">Long-form</option></Select>
        </Field>
        <ErrorText error={gen.error} />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button disabled={topic.trim().length < 3} loading={gen.isPending} onClick={() => gen.mutate(undefined, { onSuccess: (r) => onDone(r.run_id) })}>Start production</Button>
        </div>
      </div>
    </Dialog>
  );
}
