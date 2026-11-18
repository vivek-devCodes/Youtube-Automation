"use client";
import { CheckCircle2, KeyRound, XCircle } from "lucide-react";
import { useState } from "react";
import { PageHeader } from "@/components/app-shell";
import { Badge, Button, Card, CardTitle, ErrorText, Field, Input, Switch, Textarea } from "@/components/ui";
import { useAction, useApi } from "@/hooks/use-api";
import { api } from "@/services/api";
import type { Provider } from "@/types";

const KINDS = { llm: "Language models (research, scripts, SEO)", tts: "Text-to-speech", image: "Image generation", video: "AI video clips" };

interface Usage { month_to_date: number; monthly_budget: number; budget_mode: string; by_provider: { provider: string; calls: number; cost_usd: number }[];
  per_video: { video_id: number; cost_usd: number }[] }
interface Estimate { lines: { kind: string; provider: string; cost_usd: number }[]; total_usd: number; budget_remaining_usd: number; videos_affordable: number | null }

export default function AIConfig() {
  const provs = useApi<Provider[]>("/providers");
  const usage = useApi<Usage>("/usage");
  const estimate = useAction((b: { format: string; seconds: number }) => api.post<Estimate>("/usage/estimate", b));
  return (
    <>
      <PageHeader title="AI Configuration" description="Choose providers and models, test connections, and watch costs. Keys are encrypted server-side and never shown again." />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardTitle>Costs this month</CardTitle>
          <p className="mt-2 text-2xl font-semibold">${usage.data?.month_to_date.toFixed(4) ?? "0"} <span className="text-sm font-normal text-muted-foreground">of ${usage.data?.monthly_budget} ({usage.data?.budget_mode} mode)</span></p>
          <div className="mt-2 flex flex-wrap gap-2 text-xs">{usage.data?.by_provider.map((p) => <Badge key={p.provider}>{p.provider}: {p.calls} calls · ${p.cost_usd}</Badge>)}</div>
        </Card>
        <Card>
          <CardTitle>Estimate before producing</CardTitle>
          <div className="mt-2 flex gap-2">
            <Button size="sm" variant="outline" onClick={() => estimate.mutate({ format: "short", seconds: 45 })}>45s Short</Button>
            <Button size="sm" variant="outline" onClick={() => estimate.mutate({ format: "long", seconds: 480 })}>8 min video</Button>
          </div>
          {estimate.data && (
            <div className="mt-2 text-sm">
              {estimate.data.lines.map((l) => <div key={l.kind}>{l.kind} ({l.provider}): ${l.cost_usd}</div>)}
              <div className="mt-1 font-medium">≈ ${estimate.data.total_usd} per video{estimate.data.videos_affordable != null && ` · budget covers ~${estimate.data.videos_affordable}`}</div>
            </div>
          )}
        </Card>
      </div>
      {(Object.keys(KINDS) as (keyof typeof KINDS)[]).map((k) => (
        <section key={k} className="mt-6">
          <h2 className="mb-2 font-semibold">{KINDS[k]}</h2>
          <div className="grid gap-3 md:grid-cols-2">
            {provs.data?.filter((p) => p.kind === k).map((p) => <ProviderCard key={p.id} p={p} />)}
          </div>
        </section>
      ))}
      <Card className="mt-6 text-sm">
        <CardTitle>Hardware notes</CardTitle>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">
          <li><b>Ollama</b>: 8B models need ~8 GB free RAM (16 GB recommended); a GPU makes them 5–20× faster.</li>
          <li><b>ComfyUI images</b> (SDXL/Flux): NVIDIA GPU with 8–12 GB VRAM.</li>
          <li><b>Wan 2.x / LTX-Video clips</b>: NVIDIA GPU with 12–24 GB VRAM; minutes per clip. Without one, keep “No AI video clips”.</li>
          <li><b>Kokoro TTS</b> runs on CPU (Kokoro-FastAPI Docker image); <b>Piper</b> runs on any CPU.</li>
        </ul>
      </Card>
    </>
  );
}

function ProviderCard({ p }: { p: Provider }) {
  const [key, setKey] = useState("");
  const [url, setUrl] = useState(p.base_url ?? "");
  const [model, setModel] = useState(p.model?.model_name ?? "");
  const [cin, setCin] = useState(String(p.model?.cost_per_1k_input ?? 0));
  const [cout, setCout] = useState(String(p.model?.cost_per_1k_output ?? 0));
  const [unit, setUnit] = useState(String(p.model?.cost_per_unit ?? 0));
  const [workflow, setWorkflow] = useState("");
  const save = useAction((extra: Record<string, unknown> = {}) => api.patch(`/providers/${p.id}`, {
    ...(key ? { api_key: key } : {}), base_url: url, model_name: model, cost_per_1k_input: Number(cin), cost_per_1k_output: Number(cout),
    cost_per_unit: Number(unit), ...(workflow ? { config: { workflow: JSON.parse(workflow) } } : {}), ...extra,
  }), ["/providers"]);
  const test = useAction(() => api.post(`/providers/${p.id}/test`), ["/providers"]);
  const toggle = useAction((b: Record<string, unknown>) => api.patch(`/providers/${p.id}`, b), ["/providers"]);
  const hasUrl = ["ollama", "kokoro", "piper", "comfyui"].includes(p.name);
  const isLLM = p.kind === "llm" && p.name !== "mock";
  return (
    <Card className="space-y-3 p-4">
      <div className="flex items-center justify-between">
        <div className="font-medium">{p.display_name}</div>
        <div className="flex items-center gap-1">
          {p.is_default && <Badge tone="violet">default</Badge>}
          {p.is_paid ? <Badge tone="amber">paid</Badge> : <Badge tone="green">free</Badge>}
          {p.health_status === "ok" ? <CheckCircle2 className="h-4 w-4 text-emerald-500" /> : p.health_status === "error" ? <XCircle className="h-4 w-4 text-red-500" /> : null}
        </div>
      </div>
      {p.health_message && <p className={`text-xs ${p.health_status === "error" ? "text-red-600" : "text-muted-foreground"}`}>{p.health_message}</p>}
      <div className="flex flex-wrap gap-4">
        <Switch checked={p.enabled} onChange={(v) => toggle.mutate({ enabled: v })} label="Enabled" />
        <Switch checked={p.is_default} disabled={!p.enabled || p.is_default} onChange={() => toggle.mutate({ is_default: true })} label="Use as default" />
      </div>
      {p.needs_key && (
        <Field label="API key" hint={p.api_key_set ? `Saved: ${p.api_key_masked}. Paste a new one to replace it.` : "Not set. Also accepted via .env."}>
          <div className="flex items-center gap-2"><KeyRound className="h-4 w-4 text-muted-foreground" />
            <Input type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder="paste key" /></div>
        </Field>
      )}
      {hasUrl && <Field label="Base URL"><Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="http://localhost:…" /></Field>}
      {p.name !== "mock" && p.name !== "none" && p.name !== "procedural" && <Field label="Model / voice"><Input value={model} onChange={(e) => setModel(e.target.value)} /></Field>}
      {isLLM && p.is_paid && (
        <div className="grid grid-cols-2 gap-2">
          <Field label="$ per 1k input tokens"><Input value={cin} onChange={(e) => setCin(e.target.value)} /></Field>
          <Field label="$ per 1k output tokens"><Input value={cout} onChange={(e) => setCout(e.target.value)} /></Field>
        </div>
      )}
      {!isLLM && p.is_paid && <Field label={p.kind === "tts" ? "$ per 1k characters" : "$ per image"}><Input value={unit} onChange={(e) => setUnit(e.target.value)} /></Field>}
      {p.name === "comfyui" && (
        <Field label="Workflow JSON (API format)" hint={`Use {{prompt}}, {{width}}, {{height}}, {{seed}}${p.kind === "video" ? ", {{frames}}" : ""} placeholders.${p.config?.workflow ? " A workflow is saved." : ""}`}>
          <Textarea rows={3} value={workflow} onChange={(e) => setWorkflow(e.target.value)} placeholder='{"3": {"class_type": "KSampler", ...}}' />
        </Field>
      )}
      <ErrorText error={save.error ?? test.error ?? toggle.error} />
      <div className="flex gap-2">
        <Button size="sm" loading={save.isPending} onClick={() => save.mutate({}, { onSuccess: () => setKey("") })}>Save</Button>
        <Button size="sm" variant="outline" loading={test.isPending} onClick={() => test.mutate(undefined)}>Test connection</Button>
      </div>
    </Card>
  );
}
