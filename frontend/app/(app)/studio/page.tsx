"use client";
import { CheckCircle2, Circle, Loader2, RotateCcw, ShieldCheck, XCircle } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { PageHeader } from "@/components/app-shell";
import { PublishDialog } from "@/components/publish-dialog";
import { QAReportView } from "@/components/qa-report";
import { Badge, Button, Card, CardTitle, Empty, ErrorText, Field, Input, StatusBadge, Textarea, cn } from "@/components/ui";
import { useAction, useApi } from "@/hooks/use-api";
import { api, mediaUrl } from "@/services/api";
import type { Run, RunDetail, Scene } from "@/types";

const STEP_LABELS: Record<string, string> = {
  research: "Research", script: "Script", script_review: "Script review", originality: "Originality & copyright", seo: "SEO",
  voice: "Voice", visuals: "Visuals", render: "Render", qa: "Quality check", approval: "Approval", publish: "Upload",
};

export default function StudioPage() {
  return <Suspense><Studio /></Suspense>;
}

function Studio() {
  const params = useSearchParams();
  const router = useRouter();
  const runId = params.get("run");
  const runs = useApi<Run[]>("/content", { refetchInterval: 10_000 });
  return (
    <>
      <PageHeader title="Content Studio" description="Every production run, step by step. Edit scripts and metadata before anything is rendered or published." />
      <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
        <Card className="max-h-[75vh] overflow-auto p-2">
          {!runs.data?.length && <p className="p-3 text-sm text-muted-foreground">No productions yet. Approve a topic on the Trends page.</p>}
          {runs.data?.map((r) => (
            <button key={r.id} onClick={() => router.push(`/studio?run=${r.id}`)}
              className={cn("block w-full rounded-md p-2 text-left text-sm hover:bg-muted", String(r.id) === runId && "bg-primary/10")}>
              <div className="line-clamp-2 font-medium">{r.title || r.idea?.title}</div>
              <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                <StatusBadge status={r.status} /> {r.current_step && STEP_LABELS[r.current_step]} · {r.idea?.format}
              </div>
            </button>
          ))}
        </Card>
        {runId ? <RunView id={Number(runId)} /> : <Empty title="Select a production">Pick a run on the left to see its script, assets and checks.</Empty>}
      </div>
    </>
  );
}

function RunView({ id }: { id: number }) {
  const { data: run, error } = useApi<RunDetail>(`/content/${id}`, {
    refetchInterval: (q) => (["running", "pending", "retry_scheduled"].includes((q.state.data as RunDetail | undefined)?.status ?? "") ? 4000 : 15000),
  });
  const retry = useAction((from_step?: string) => api.post(`/content/${id}/retry`, { from_step }), ["/content"]);
  const cancel = useAction(() => api.post(`/content/${id}/cancel`), ["/content"]);
  const decide = useAction((approve: boolean) => api.post(`/content/${id}/script-decision`, { approve }), ["/content"]);
  const [publishOpen, setPublishOpen] = useState(false);
  if (error) return <ErrorText error={error} />;
  if (!run) return <Loader2 className="h-5 w-5 animate-spin" />;
  const steps = Object.keys(STEP_LABELS);
  const waitingScript = run.status === "waiting_approval" && run.current_step === "script_review";
  const pendingVideoApproval = run.approvals.find((a) => a.kind === "video_publish" && a.status === "pending");
  const video = run.video;
  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h2 className="text-lg font-semibold">{run.metadata?.title ?? run.script?.title ?? run.idea.title}</h2>
            <div className="mt-1 flex flex-wrap gap-2 text-xs text-muted-foreground">
              <StatusBadge status={run.status} /> <Badge>{run.idea.format}</Badge> target {run.idea.target_duration_seconds}s
              {run.script && <span>· written by {run.script.llm_provider}/{run.script.llm_model}</span>}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {["failed", "paused", "retry_scheduled"].includes(run.status) && <Button size="sm" loading={retry.isPending} onClick={() => retry.mutate(undefined)}><RotateCcw className="h-4 w-4" /> Retry</Button>}
            {!["succeeded", "cancelled", "failed"].includes(run.status) && <Button size="sm" variant="outline" onClick={() => cancel.mutate(undefined)}>Cancel</Button>}
            {run.script && !["running"].includes(run.status) && <Button size="sm" variant="outline" onClick={() => retry.mutate("voice")}>Re-render</Button>}
          </div>
        </div>
        <ol className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
          {steps.map((s) => {
            const st = run.steps[s]?.status ?? "pending";
            return (
              <li key={s} className="flex items-center gap-1.5 text-xs" title={run.steps[s]?.error ?? run.steps[s]?.note ?? ""}>
                {st === "done" ? <CheckCircle2 className="h-4 w-4 text-emerald-500" /> : st === "running" ? <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
                  : st === "error" ? <XCircle className="h-4 w-4 text-red-500" /> : st === "waiting" ? <Circle className="h-4 w-4 fill-amber-400 text-amber-400" />
                  : <Circle className="h-4 w-4 text-muted-foreground" />}
                {STEP_LABELS[s]}
              </li>
            );
          })}
        </ol>
        {run.last_error && <p className="mt-3 rounded bg-red-50 p-2 text-xs text-red-700 dark:bg-red-900/30 dark:text-red-300">{run.last_error}</p>}
        {waitingScript && (
          <div className="mt-4 flex flex-wrap items-center gap-2 rounded-md bg-amber-50 p-3 text-sm dark:bg-amber-900/30">
            Review and edit the script below, then:
            <Button size="sm" variant="success" loading={decide.isPending} onClick={() => decide.mutate(true)}>Approve script & produce</Button>
            <Button size="sm" variant="destructive" onClick={() => decide.mutate(false)}>Reject</Button>
          </div>
        )}
        {pendingVideoApproval && video && (
          <div className="mt-4 flex flex-wrap items-center gap-2 rounded-md bg-amber-50 p-3 text-sm dark:bg-amber-900/30">
            Video passed QA ({video.quality_score}). Watch it, then
            <Button size="sm" variant="success" onClick={() => setPublishOpen(true)}>Approve & publish…</Button>
          </div>
        )}
      </Card>

      {video?.file_path && (
        <Card>
          <CardTitle>Preview {video.status && <StatusBadge status={video.status} />}</CardTitle>
          <div className="mt-3 flex flex-wrap gap-4">
            <video controls className={cn("rounded-md bg-black", video.format === "short" ? "h-[480px]" : "w-full max-w-2xl")} src={mediaUrl(video.file_path)} />
            {video.youtube_video_id && (
              <p className="text-sm">{video.sandbox ? <>Sandbox upload id <code>{video.youtube_video_id}</code> (simulated)</>
                : <a className="text-primary underline" href={video.youtube_url ?? "#"} target="_blank" rel="noreferrer">Open on YouTube</a>}</p>
            )}
          </div>
        </Card>
      )}

      {run.script && <ScriptEditor run={run} />}
      {run.metadata && <MetadataEditor run={run} />}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardTitle className="flex items-center gap-2"><ShieldCheck className="h-4 w-4" /> Originality & copyright</CardTitle>
          {run.script?.compliance_report?.checks ? (
            <ul className="mt-2 space-y-1 text-sm">
              <li>Originality score: <b>{run.script.originality_score ?? "—"}</b></li>
              {run.script.compliance_report.checks.map((c) => (
                <li key={c.name} className="flex gap-2">{c.passed ? <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" /> : <XCircle className="h-4 w-4 shrink-0 text-red-500" />}
                  <span><b>{c.name.replace(/_/g, " ")}</b> — {c.detail}</span></li>
              ))}
            </ul>
          ) : <p className="mt-2 text-sm text-muted-foreground">Runs after the script is written.</p>}
          {run.provenance.length > 0 && (
            <details className="mt-3 text-xs">
              <summary className="cursor-pointer">Asset provenance ({run.provenance.length})</summary>
              <ul className="mt-1 space-y-1">{run.provenance.map((p) => <li key={p.id}>{p.kind} · {p.provider} · {p.license.license_type} {p.license.verified && "✓"} — {p.license.notes}</li>)}</ul>
            </details>
          )}
        </Card>
        <Card>
          <CardTitle>Quality assurance</CardTitle>
          {video?.qa_report?.checks ? <QAReportView report={video.qa_report} /> : <p className="mt-2 text-sm text-muted-foreground">Runs after rendering.</p>}
        </Card>
      </div>

      <Card>
        <CardTitle>Research</CardTitle>
        <p className="mt-2 text-sm">{run.idea.research_summary || "—"}</p>
        <ul className="mt-2 space-y-1 text-xs">
          {run.sources.map((s) => <li key={s.id}><a className="text-primary underline" href={s.url} target="_blank" rel="noreferrer">{s.title || s.url}</a> · {s.publisher}</li>)}
        </ul>
      </Card>
      {publishOpen && video && pendingVideoApproval && <PublishDialog approvalId={pendingVideoApproval.id} suggested={pendingVideoApproval.payload.suggested_slot} onClose={() => setPublishOpen(false)} />}
      <p className="text-xs text-muted-foreground">Need the full library? <Link className="text-primary" href="/library">Video Library</Link></p>
    </div>
  );
}

function ScriptEditor({ run }: { run: RunDetail }) {
  const [edits, setEdits] = useState<Record<number, Partial<Scene>>>({});
  useEffect(() => setEdits({}), [run.script?.id]);
  const save = useAction(() => api.patch(`/content/${run.id}`, { scenes: Object.entries(edits).map(([id, e]) => ({ id: Number(id), ...e })) }), ["/content"]);
  const busy = run.status === "running";
  const dirty = Object.keys(edits).length > 0;
  return (
    <Card>
      <div className="flex items-center justify-between">
        <CardTitle>Script & scenes <span className="font-normal text-muted-foreground">≈ {run.script?.estimated_duration_seconds}s</span></CardTitle>
        <Button size="sm" disabled={!dirty || busy} loading={save.isPending} onClick={() => save.mutate(undefined, { onSuccess: () => setEdits({}) })}>Save edits</Button>
      </div>
      {busy && <p className="mt-1 text-xs text-muted-foreground">Editing unlocks when the current step finishes.</p>}
      <ErrorText error={save.error} />
      <div className="mt-3 space-y-3">
        {run.scenes?.map((s) => {
          const e = edits[s.id] ?? {};
          const set = (k: keyof Scene, v: string) => setEdits({ ...edits, [s.id]: { ...e, [k]: v } });
          return (
            <div key={s.id} className="grid gap-3 rounded-md border border-border p-3 md:grid-cols-[1fr_140px]">
              <div className="space-y-2">
                <div className="text-xs font-medium text-muted-foreground">Scene {s.idx + 1} {s.idx === 0 && "· hook"}</div>
                <Textarea rows={2} disabled={busy} value={e.narration ?? s.narration} onChange={(ev) => set("narration", ev.target.value)} aria-label={`Narration scene ${s.idx + 1}`} />
                <div className="grid gap-2 sm:grid-cols-2">
                  <Input disabled={busy} value={e.on_screen_text ?? s.on_screen_text} onChange={(ev) => set("on_screen_text", ev.target.value)} placeholder="On-screen text" />
                  <Input disabled={busy} value={e.visual_prompt ?? s.visual_prompt} onChange={(ev) => set("visual_prompt", ev.target.value)} placeholder="Visual prompt" />
                </div>
                {s.voiceover && <audio controls preload="none" className="h-8 w-full" src={mediaUrl(s.voiceover.path)} />}
              </div>
              {s.image ? <img src={mediaUrl(s.image.path)} alt={`scene ${s.idx + 1}`} className="w-full rounded-md object-cover" /> : <div className="rounded-md bg-muted" />}
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function MetadataEditor({ run }: { run: RunDetail }) {
  const m = run.metadata!;
  const [title, setTitle] = useState(m.title);
  const [desc, setDesc] = useState(m.description);
  const [tags, setTags] = useState(m.tags.join(", "));
  const [thumb, setThumb] = useState(m.thumbnail_text);
  const [playlist, setPlaylist] = useState(m.playlist_id ?? "");
  const save = useAction(() => api.patch(`/content/${run.id}`, { metadata: { title, description: desc, tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
    thumbnail_text: thumb, playlist_id: playlist || null } }), ["/content"]);
  const thumbPath = run.video?.thumbnail ?? (run.video?.file_path ? run.video.file_path.replace("final.mp4", "thumbnail.jpg") : null);
  return (
    <Card>
      <div className="flex items-center justify-between">
        <CardTitle>SEO & metadata</CardTitle>
        <Button size="sm" loading={save.isPending} onClick={() => save.mutate(undefined)}>Save metadata</Button>
      </div>
      <ErrorText error={save.error} />
      <div className="mt-3 grid gap-3 md:grid-cols-[1fr_260px]">
        <div className="space-y-3">
          <Field label={`Title (${title.length}/100)`}><Input maxLength={100} value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
          <Field label="Description"><Textarea rows={6} value={desc} onChange={(e) => setDesc(e.target.value)} /></Field>
          <Field label="Tags (comma separated)"><Input value={tags} onChange={(e) => setTags(e.target.value)} /></Field>
          <div className="flex flex-wrap gap-1">{m.hashtags.map((h) => <Badge key={h} tone="blue">{h}</Badge>)}</div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Thumbnail text" hint="Changing it re-renders the thumbnail."><Input value={thumb} onChange={(e) => setThumb(e.target.value)} /></Field>
            <Field label="Playlist ID (optional)" hint="Needs ENABLE_PLAYLIST_SCOPE."><Input value={playlist} onChange={(e) => setPlaylist(e.target.value)} /></Field>
          </div>
          <p className="text-xs text-muted-foreground">Audience: {m.made_for_kids ? "Made for Kids" : "Not made for kids"} · AI disclosure: {m.contains_synthetic_media ? "on" : "off"}</p>
        </div>
        {thumbPath && <img src={`${mediaUrl(thumbPath)}?v=${run.updated_at}`} alt="thumbnail" className="w-full rounded-md" />}
      </div>
    </Card>
  );
}
