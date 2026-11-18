"use client";
import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ExternalLink, FlaskConical, Loader2, Sparkles, Youtube } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ChannelConfigForm, LanguageForm, NicheForm, PublishingForm, VideoForm, type ChannelPatch,
} from "@/components/channel-forms";
import { ProviderPicker } from "@/components/provider-picker";
import { Badge, Button, Card, ErrorText, Field, Input, Progress, Switch, cn } from "@/components/ui";
import { useApi, useCatalog, useMe } from "@/hooks/use-api";
import { api } from "@/services/api";
import type { Channel } from "@/types";

const STEPS = ["Welcome", "YouTube channel", "Channel setup", "Content niche", "Languages", "Video format", "Publishing", "Budget",
  "AI providers", "Review & activate"];

export default function Onboarding() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const me = useMe();
  const cat = useCatalog();
  const channels = useApi<Channel[]>(me.data ? "/channels" : null);
  const [step, setStep] = useState(0);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [patch, setPatch] = useState<ChannelPatch>({});
  const [hasChannel, setHasChannel] = useState<"yes" | "no" | null>(null);
  const [budget, setBudget] = useState({ mode: "free", limit: 0 });
  const [providers, setProviders] = useState<Record<string, string>>({});
  const [activate, setActivate] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (me.isError) router.replace("/login");
    const s = me.data?.onboarding_state as { step?: number; budget?: typeof budget } | undefined;
    if (s?.step) setStep(s.step);
    if (s?.budget) setBudget(s.budget);
  }, [me.data, me.isError, router]);

  useEffect(() => {
    if (!activeId && channels.data?.length) setActiveId(channels.data[channels.data.length - 1].id);
    const q = new URLSearchParams(window.location.search);
    if (q.get("connected")) setStep((s) => Math.max(s, 2));
  }, [channels.data, activeId]);

  const channel = channels.data?.find((c) => c.id === activeId);

  async function go(next: number) {
    setError(null);
    setBusy(true);
    try {
      if (channel && Object.keys(patch).length) {
        await api.patch(`/channels/${channel.id}`, patch);
        setPatch({});
        await channels.refetch();
      }
      if (step === 3 && channel && !(patch.niches?.length || patch.custom_niches?.length || channel.niches.length)) {
        throw new Error("Pick at least one niche for this channel");
      }
      await api.patch("/onboarding", { step: next, data: { budget } });
      setStep(next);
      window.scrollTo(0, 0);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  async function finish() {
    setBusy(true);
    setError(null);
    try {
      await api.post("/onboarding/complete", { budget_mode: budget.mode, monthly_budget_usd: budget.limit, activate, confirm, providers });
      await queryClient.invalidateQueries({ queryKey: ["/auth/me"] }); // otherwise the shell still sees "not onboarded"
      await queryClient.refetchQueries({ queryKey: ["/auth/me"] });
      router.replace("/dashboard");
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  }

  const needsChannel = step >= 2 && step <= 6 && !channel;

  return (
    <div className="mx-auto max-w-3xl p-4 md:p-10">
      <div className="mb-6 flex items-center gap-2 text-lg font-semibold"><Sparkles className="h-5 w-5 text-primary" /> AI YouTube Studio — setup</div>
      <div className="mb-2 flex justify-between text-xs text-muted-foreground"><span>Step {step + 1} of {STEPS.length}: {STEPS[step]}</span></div>
      <Progress value={((step + 1) / STEPS.length) * 100} className="mb-6" />

      <Card className="space-y-5 p-6">
        {step === 0 && (
          <div className="space-y-4">
            <h1 className="text-2xl font-semibold">Welcome to your AI YouTube Automation Studio.</h1>
            <p>Let&apos;s create your automated content business. This application will discover trends, generate original videos and help manage your YouTube channels.</p>
            <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
              <li>Trending videos are used for <b>research and inspiration only</b> — every script, voice, image and music track is newly generated.</li>
              <li>Nothing is published without your approval unless you explicitly switch that on later.</li>
              <li>No guarantees: views, subscribers and revenue depend on YouTube, your audience and content quality.</li>
            </ul>
          </div>
        )}

        {step === 1 && (
          <div className="space-y-4">
            <h2 className="text-xl font-semibold">Do you already have a YouTube channel?</h2>
            <div className="grid gap-3 sm:grid-cols-2">
              {(["yes", "no"] as const).map((v) => (
                <button key={v} onClick={() => setHasChannel(v)}
                  className={cn("rounded-lg border p-4 text-left", hasChannel === v ? "border-primary bg-primary/10" : "border-border hover:bg-muted")}>
                  <div className="font-medium">{v === "yes" ? "Yes, connect it" : "No, help me create one"}</div>
                </button>
              ))}
            </div>
            {hasChannel === "no" && (
              <div className="space-y-2 rounded-md bg-muted p-4 text-sm">
                <p className="font-medium">Create your channel on YouTube (takes 2 minutes):</p>
                <ol className="list-decimal space-y-1 pl-5">
                  <li>Open <a className="text-primary underline" href="https://www.youtube.com/create_channel" target="_blank" rel="noreferrer">youtube.com/create_channel <ExternalLink className="inline h-3 w-3" /></a> and sign in with the Google account you want to use.</li>
                  <li>Choose a <b>name</b> that matches your niche (short, memorable, easy to spell) and a unique <b>@handle</b>.</li>
                  <li>Upload a simple square <b>profile picture</b> (your logo, 800×800px).</li>
                  <li>Verify your phone at <a className="text-primary underline" href="https://www.youtube.com/verify" target="_blank" rel="noreferrer">youtube.com/verify</a> — needed for custom thumbnails and videos over 15 minutes.</li>
                  <li>Come back here and choose <b>Connect with Google</b>.</li>
                </ol>
                <p className="text-xs text-muted-foreground">YouTube&apos;s public API cannot create channels, so this one step is manual.</p>
              </div>
            )}
            {hasChannel && <ConnectButtons googleReady={!!cat.data?.google_oauth_configured} onSandbox={async () => {
              const ch = await api.post<Channel>("/channels/connect", { mode: "sandbox", title: "My Practice Channel" });
              await channels.refetch();
              setActiveId(ch.id);
            }} />}
            <ChannelList channels={channels.data ?? []} activeId={activeId} onPick={setActiveId} />
          </div>
        )}

        {needsChannel && <p className="text-sm">Connect a channel (or create a sandbox channel) in step 2 first.</p>}
        {step === 2 && channel && <><h2 className="text-xl font-semibold">Configure “{channel.title}”</h2><ChannelConfigForm channel={channel} value={patch} onChange={setPatch} /></>}
        {step === 3 && channel && <><h2 className="text-xl font-semibold">Pick a content niche</h2><NicheForm channel={channel} value={patch} onChange={setPatch} /></>}
        {step === 4 && channel && <><h2 className="text-xl font-semibold">Languages</h2><LanguageForm channel={channel} value={patch} onChange={setPatch} /></>}
        {step === 5 && channel && <><h2 className="text-xl font-semibold">Video format & style</h2><VideoForm channel={channel} value={patch} onChange={setPatch} /></>}
        {step === 6 && channel && <><h2 className="text-xl font-semibold">Publishing</h2><PublishingForm channel={channel} value={patch} onChange={setPatch} /></>}

        {step === 7 && (
          <div className="space-y-4">
            <h2 className="text-xl font-semibold">Budget</h2>
            <div className="grid gap-3 sm:grid-cols-2">
              {Object.entries(cat.data?.budget_modes ?? {}).map(([k, m]) => (
                <button key={k} onClick={() => setBudget({ ...budget, mode: k })}
                  className={cn("rounded-lg border p-4 text-left text-sm", budget.mode === k ? "border-primary bg-primary/10" : "border-border hover:bg-muted")}>
                  <div className="font-medium">{m.label}</div>
                  <div className="mt-1 text-xs text-muted-foreground">LLM: {m.llm} · Voice: {m.tts} · Images: {m.image}{m.video !== "none" ? ` · Video: ${m.video}` : ""}</div>
                </button>
              ))}
            </div>
            <Field label="Monthly spending limit (USD)" hint="Paid generation pauses automatically when this is reached. Free mode never makes paid calls.">
              <Input type="number" min={0} step={1} value={budget.limit} onChange={(e) => setBudget({ ...budget, limit: Number(e.target.value) })} disabled={budget.mode === "free"} />
            </Field>
            {budget.mode === "free" && (
              <p className="rounded-md bg-muted p-3 text-xs">
                Free mode runs on your computer. Scripts need <b>Ollama</b> (8 GB+ RAM; 16 GB recommended for 8B models). Local AI <b>video</b> models (Wan, LTX)
                need an NVIDIA GPU with 12–24 GB VRAM — without one, videos use animated original illustrations and motion graphics instead.
              </p>
            )}
          </div>
        )}

        {step === 8 && (
          <div className="space-y-4">
            <h2 className="text-xl font-semibold">AI providers</h2>
            <p className="text-sm text-muted-foreground">Pick a default for each capability. API keys are encrypted on the server and never shown again. You can change all of this later in AI Configuration.</p>
            <ProviderPicker budgetMode={budget.mode} value={providers} onChange={setProviders} />
          </div>
        )}

        {step === 9 && (
          <Summary channels={channels.data ?? []} budget={budget} providers={providers} activate={activate} setActivate={setActivate}
            confirm={confirm} setConfirm={setConfirm} />
        )}

        <ErrorText error={error} />
        <div className="flex justify-between border-t border-border pt-4">
          <Button variant="outline" disabled={step === 0 || busy} onClick={() => go(step - 1)}>Back</Button>
          {step < STEPS.length - 1 ? (
            <Button loading={busy} disabled={(step === 1 && !channels.data?.length) || needsChannel} onClick={() => go(step + 1)}>Continue</Button>
          ) : (
            <Button loading={busy} disabled={!confirm} onClick={finish}>{activate ? "Activate automation" : "Finish setup"}</Button>
          )}
        </div>
      </Card>
    </div>
  );
}

function ConnectButtons({ googleReady, onSandbox }: { googleReady: boolean; onSandbox: () => Promise<void> }) {
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Button disabled={!googleReady || busy} onClick={async () => {
          setBusy(true);
          try {
            const r = await api.post<{ auth_url: string }>("/channels/connect", { mode: "google" });
            window.location.href = r.auth_url;
          } catch (e) { setErr(e); setBusy(false); }
        }}><Youtube className="h-4 w-4" /> Connect with Google</Button>
        <Button variant="outline" loading={busy} onClick={async () => { setBusy(true); try { await onSandbox(); } catch (e) { setErr(e); } setBusy(false); }}>
          <FlaskConical className="h-4 w-4" /> Create a sandbox practice channel
        </Button>
      </div>
      {!googleReady && (
        <p className="rounded-md bg-amber-50 p-3 text-xs text-amber-800 dark:bg-amber-900/30 dark:text-amber-200">
          Google sign-in isn&apos;t configured yet. An administrator must create OAuth credentials and add <code>GOOGLE_CLIENT_ID</code> / <code>GOOGLE_CLIENT_SECRET</code> to
          the <code>.env</code> file (step-by-step guide: <code>docs/SETUP_GOOGLE.md</code>). Meanwhile you can try everything with a sandbox channel — it never uploads to YouTube.
        </p>
      )}
      <p className="text-xs text-muted-foreground">We request only: upload videos, read your channel, and read analytics. We never get your password.</p>
      <ErrorText error={err} />
    </div>
  );
}

function ChannelList({ channels, activeId, onPick }: { channels: Channel[]; activeId: number | null; onPick: (id: number) => void }) {
  if (!channels.length) return null;
  return (
    <div className="space-y-2">
      <p className="text-sm font-medium">Connected channels — select the one to configure:</p>
      {channels.map((c) => (
        <button key={c.id} onClick={() => onPick(c.id)}
          className={cn("flex w-full items-center gap-3 rounded-md border p-3 text-left", activeId === c.id ? "border-primary bg-primary/10" : "border-border")}>
          {c.thumbnail_url ? <img src={c.thumbnail_url} alt="" className="h-9 w-9 rounded-full" /> : <div className="h-9 w-9 rounded-full bg-muted" />}
          <div className="flex-1">
            <div className="font-medium">{c.title} {c.is_sandbox && <Badge tone="amber">sandbox</Badge>}</div>
            <div className="text-xs text-muted-foreground">{c.youtube_channel_id ?? "local practice channel — uploads are simulated"}</div>
          </div>
          {activeId === c.id && <CheckCircle2 className="h-5 w-5 text-primary" />}
        </button>
      ))}
    </div>
  );
}

function Summary({ channels, budget, providers, activate, setActivate, confirm, setConfirm }: {
  channels: Channel[]; budget: { mode: string; limit: number }; providers: Record<string, string>;
  activate: boolean; setActivate: (v: boolean) => void; confirm: boolean; setConfirm: (v: boolean) => void;
}) {
  const cat = useCatalog();
  const provs = useApi<{ providers: Record<string, { name: string; display: string }> }>("/onboarding/summary");
  if (!provs.data) return <Loader2 className="h-5 w-5 animate-spin" />;
  return (
    <div className="space-y-4 text-sm">
      <h2 className="text-xl font-semibold">Review your setup</h2>
      {channels.map((c) => (
        <div key={c.id} className="rounded-md border border-border p-3">
          <div className="font-medium">{c.title} {c.is_sandbox && <Badge tone="amber">sandbox — simulated uploads</Badge>}</div>
          <div className="mt-1 grid gap-1 text-muted-foreground sm:grid-cols-2">
            <span>Niches: {c.niches.map((n) => n.name).join(", ") || "—"}</span>
            <span>Language: {cat.data?.languages[c.settings.language]} (voice {cat.data?.languages[c.settings.voiceover_language]})</span>
            <span>Shorts/day: {c.settings.shorts_per_day} ({c.settings.short_duration_seconds}s) · Long/week: {c.settings.long_per_week}</span>
            <span>Times: {c.settings.publish_times.join(", ")} {c.settings.timezone}</span>
            <span>Approval: {c.settings.require_approval ? "required for every video" : "not required"}</span>
            <span>Made for Kids: {c.settings.made_for_kids ? "yes" : "no"}</span>
          </div>
        </div>
      ))}
      <div className="rounded-md border border-border p-3">
        <div>Budget: <b>{cat.data?.budget_modes[budget.mode]?.label}</b>{budget.mode !== "free" && ` · limit $${budget.limit}/month`}</div>
        <div className="mt-1 text-muted-foreground">
          Providers: {["llm", "tts", "image", "video"].map((k) => `${k.toUpperCase()}: ${providers[k] ?? provs.data?.providers[k]?.name ?? "—"}`).join(" · ")}
        </div>
      </div>
      <Switch checked={activate} onChange={setActivate} label="Start automation now (trend scans every few hours and production up to your daily capacity)" />
      <label className="flex items-start gap-2">
        <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} className="mt-1" />
        <span>I have reviewed this configuration. I understand videos are AI-generated, that I am responsible for what is published on my channel, and that results are not guaranteed.</span>
      </label>
    </div>
  );
}

