"use client";
import { Eye, Film } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { PageHeader } from "@/components/app-shell";
import { Badge, Card, Empty, StatusBadge, Tabs } from "@/components/ui";
import { useApi } from "@/hooks/use-api";
import { mediaUrl } from "@/services/api";
import type { Video } from "@/types";

const FILTERS = {
  all: "",
  drafts: "in_production,rendering,rendered,qa_passed,awaiting_approval,approved,pending",
  published: "published,scheduled,uploaded",
  failed: "failed,qa_failed,rejected,cancelled",
};

export default function Library() {
  const [format, setFormat] = useState<"" | "short" | "long">("");
  const [filter, setFilter] = useState<keyof typeof FILTERS>("all");
  const q = new URLSearchParams();
  if (format) q.set("format", format);
  if (FILTERS[filter]) q.set("status", FILTERS[filter]);
  const videos = useApi<Video[]>(`/videos?${q}`, { refetchInterval: 15_000 });
  return (
    <>
      <PageHeader title="Video Library" description="Everything the studio has produced." />
      <div className="mb-4 flex flex-wrap gap-2">
        <Tabs value={filter} onChange={setFilter} items={[{ value: "all", label: "All" }, { value: "drafts", label: "Drafts" },
          { value: "published", label: "Published" }, { value: "failed", label: "Failed" }]} />
        <Tabs value={format} onChange={setFormat} items={[{ value: "", label: "All formats" }, { value: "short", label: "Shorts" }, { value: "long", label: "Long-form" }]} />
      </div>
      {!videos.data?.length ? <Empty title="No videos here yet" /> : (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-4">
          {videos.data.map((v) => (
            <Link key={v.id} href={v.run_id ? `/studio?run=${v.run_id}` : "#"}>
              <Card className="overflow-hidden p-0 transition hover:shadow-md">
                {v.thumbnail ? <img src={mediaUrl(v.thumbnail)} alt="" className="aspect-video w-full object-cover" />
                  : <div className="flex aspect-video items-center justify-center bg-muted"><Film className="h-8 w-8 text-muted-foreground" /></div>}
                <div className="space-y-1 p-3">
                  <div className="line-clamp-2 text-sm font-medium">{v.metadata?.title ?? `Video ${v.id}`}</div>
                  <div className="flex flex-wrap items-center gap-1 text-xs">
                    <StatusBadge status={v.status} />
                    <Badge>{v.format}</Badge>
                    {v.sandbox && <Badge tone="amber">sandbox</Badge>}
                    {v.quality_score != null && <Badge tone={v.qa_report?.passed ? "green" : "red"}>QA {v.quality_score}</Badge>}
                  </div>
                  {v.analytics && <div className="flex items-center gap-1 text-xs text-muted-foreground"><Eye className="h-3 w-3" /> {v.analytics.views.toLocaleString()} views</div>}
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
