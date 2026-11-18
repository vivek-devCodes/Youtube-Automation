"use client";
import { RefreshCw } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { PageHeader } from "@/components/app-shell";
import { Badge, Button, Card, CardTitle, Empty } from "@/components/ui";
import { useAction, useApi } from "@/hooks/use-api";
import { api } from "@/services/api";

interface Overview { series: { date: string; views: number; watch_hours: number; subscribers: number | null; ctr: number | null; retention: number | null; revenue: number | null }[];
  insights: { summary?: string; best?: Record<string, string>; winning_keywords?: string[]; videos_analyzed?: number; updated_at?: string } }
interface VideoRow { video_id: number; title: string; format: string; niche: string; views: number; likes: number | null; avg_view_percentage: number | null;
  watch_time_minutes: number | null; subscribers_gained: number | null; source: string; window: string }

export default function Analytics() {
  const ov = useApi<Overview>("/analytics/overview?days=90");
  const vids = useApi<{ videos: VideoRow[]; by_niche: { niche: string; videos: number; views: number }[] }>("/analytics/videos");
  const collect = useAction(() => api.post("/analytics/collect"), ["/analytics"]);
  const series = ov.data?.series ?? [];
  const ins = ov.data?.insights;
  const charts: { key: keyof Overview["series"][number]; label: string }[] = [
    { key: "views", label: "Views over time" }, { key: "subscribers", label: "Subscribers" }, { key: "watch_hours", label: "Watch time (hours)" },
    { key: "retention", label: "Average % viewed (retention)" }, { key: "ctr", label: "Click-through rate (%)" }, { key: "revenue", label: "Estimated revenue ($)" },
  ];
  return (
    <>
      <PageHeader title="Analytics" description="Collected daily from the YouTube Data & Analytics APIs (sandbox channels use simulated numbers)."
        actions={<Button variant="outline" loading={collect.isPending} onClick={() => collect.mutate(undefined)}><RefreshCw className="h-4 w-4" /> Collect now</Button>} />
      {ins?.summary && (
        <Card className="mb-4">
          <CardTitle>What the optimisation agent learned {ins.videos_analyzed ? `(${ins.videos_analyzed} videos)` : ""}</CardTitle>
          <p className="mt-2 text-sm">{ins.summary}</p>
          {!!ins.winning_keywords?.length && <div className="mt-2 flex flex-wrap gap-1">{ins.winning_keywords.map((k) => <Badge key={k} tone="violet">{k}</Badge>)}</div>}
          <p className="mt-2 text-xs text-muted-foreground">These insights feed into topic scoring and script writing. The agent never deletes videos or edits published metadata.</p>
        </Card>
      )}
      {!series.length ? <Empty title="No analytics yet">Publish a video, then click “Collect now”.</Empty> : (
        <div className="grid gap-4 lg:grid-cols-2">
          {charts.map(({ key, label }) => {
            const has = series.some((s) => s[key] != null);
            return (
              <Card key={key}>
                <CardTitle>{label}</CardTitle>
                {has ? (
                  <div className="mt-3 h-52">
                    <ResponsiveContainer>
                      <LineChart data={series}>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                        <XAxis dataKey="date" fontSize={11} />
                        <YAxis fontSize={11} />
                        <Tooltip />
                        <Line type="monotone" dataKey={key} stroke="hsl(var(--primary))" strokeWidth={2} dot={false} connectNulls />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                ) : <p className="mt-3 text-sm text-muted-foreground">Not available for your channels yet{key === "revenue" ? " (requires YPP + monetary analytics scope)" : key === "ctr" ? " (impressions/CTR are only partly exposed by the API)" : ""}.</p>}
              </Card>
            );
          })}
        </div>
      )}
      {!!vids.data?.by_niche.length && (
        <Card className="mt-4">
          <CardTitle>Views by category</CardTitle>
          <div className="mt-3 h-56">
            <ResponsiveContainer>
              <BarChart data={vids.data.by_niche}><XAxis dataKey="niche" fontSize={11} /><YAxis fontSize={11} /><Tooltip /><Bar dataKey="views" fill="hsl(var(--primary))" /></BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}
      {!!vids.data?.videos.length && (
        <Card className="mt-4">
          <CardTitle>Best-performing videos</CardTitle>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground"><tr><th className="py-2">Title</th><th>Format</th><th>Views</th><th>Likes</th><th>% viewed</th><th>Subs</th><th>Source</th></tr></thead>
              <tbody>{vids.data.videos.slice(0, 20).map((v) => (
                <tr key={v.video_id} className="border-t border-border">
                  <td className="py-2 pr-2">{v.title}</td><td>{v.format}</td><td>{v.views.toLocaleString()}</td><td>{v.likes ?? "—"}</td>
                  <td>{v.avg_view_percentage ?? "—"}</td><td>{v.subscribers_gained ?? "—"}</td><td><Badge tone={v.source === "sandbox" ? "amber" : "gray"}>{v.source}</Badge></td>
                </tr>))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  );
}
