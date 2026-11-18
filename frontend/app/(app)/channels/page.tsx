"use client";
import { FlaskConical, Youtube } from "lucide-react";
import { useEffect, useState } from "react";
import {
  ChannelConfigForm, LanguageForm, NicheForm, PublishingForm, VideoForm, type ChannelPatch,
} from "@/components/channel-forms";
import { PageHeader } from "@/components/app-shell";
import { Badge, Button, Card, Empty, ErrorText, StatusBadge, Switch, Tabs } from "@/components/ui";
import { useAction, useApi, useCatalog } from "@/hooks/use-api";
import { api } from "@/services/api";
import type { Channel } from "@/types";

type Section = "config" | "niche" | "language" | "video" | "publishing";

export default function Channels() {
  const channels = useApi<Channel[]>("/channels");
  const cat = useCatalog();
  const [sel, setSel] = useState<number | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const connect = useAction((mode: "google" | "sandbox") => api.post<{ auth_url?: string }>("/channels/connect", { mode }), ["/channels"]);

  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    if (q.get("connected")) setMsg(`Connected ${q.get("connected")} channel(s).`);
    if (q.get("oauth_error")) setMsg(`Google connection failed: ${q.get("oauth_error")}`);
  }, []);
  useEffect(() => { if (!sel && channels.data?.length) setSel(channels.data[0].id); }, [channels.data, sel]);
  const channel = channels.data?.find((c) => c.id === sel);

  return (
    <>
      <PageHeader title="Channels" description="Each channel has its own niche, language, schedule, brand and AI settings."
        actions={<>
          <Button variant="outline" onClick={() => connect.mutate("sandbox")}><FlaskConical className="h-4 w-4" /> Sandbox channel</Button>
          <Button disabled={!cat.data?.google_oauth_configured} title={cat.data?.google_oauth_configured ? "" : "Set GOOGLE_CLIENT_ID/SECRET in .env"}
            onClick={() => connect.mutate("google", { onSuccess: (r) => { if (r.auth_url) window.location.href = r.auth_url; } })}>
            <Youtube className="h-4 w-4" /> Connect YouTube channel
          </Button>
        </>} />
      {msg && <p className="mb-3 rounded-md bg-muted p-3 text-sm">{msg}</p>}
      <ErrorText error={connect.error} />
      {!channels.data?.length ? <Empty title="No channels yet" /> : (
        <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
          <div className="space-y-2">
            {channels.data.map((c) => (
              <button key={c.id} onClick={() => setSel(c.id)} className={`w-full rounded-md border p-3 text-left text-sm ${sel === c.id ? "border-primary bg-primary/10" : "border-border bg-card"}`}>
                <div className="flex items-center gap-2">
                  {c.thumbnail_url ? <img src={c.thumbnail_url} alt="" className="h-8 w-8 rounded-full" /> : <div className="h-8 w-8 rounded-full bg-muted" />}
                  <div className="min-w-0">
                    <div className="truncate font-medium">{c.title}</div>
                    <div className="flex gap-1"><StatusBadge status={c.status} />{c.is_sandbox && <Badge tone="amber">sandbox</Badge>}</div>
                  </div>
                </div>
              </button>
            ))}
          </div>
          {channel && <ChannelEditor key={channel.id} channel={channel} />}
        </div>
      )}
    </>
  );
}

function ChannelEditor({ channel }: { channel: Channel }) {
  const [section, setSection] = useState<Section>("config");
  const [patch, setPatch] = useState<ChannelPatch>({});
  const save = useAction(() => api.patch(`/channels/${channel.id}`, patch), ["/channels"]);
  const automation = useAction((v: boolean) => api.patch(`/channels/${channel.id}`, { automation_enabled: v }), ["/channels"]);
  const disconnect = useAction(() => api.del(`/channels/${channel.id}`), ["/channels"]);
  const Form = { config: ChannelConfigForm, niche: NicheForm, language: LanguageForm, video: VideoForm, publishing: PublishingForm }[section];
  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold">{channel.title}</h2>
          <p className="text-xs text-muted-foreground">{channel.youtube_channel_id ? `${channel.youtube_channel_id} · ${channel.subscriber_count} subscribers` : "Sandbox — uploads simulated locally"}</p>
        </div>
        <div className="flex items-center gap-3">
          <Switch checked={channel.automation_enabled} onChange={(v) => automation.mutate(v)} label="Automation" />
          {channel.status === "connected" && <Button size="sm" variant="outline" onClick={() => confirm("Disconnect this channel and revoke Google access? History is kept.") && disconnect.mutate(undefined)}>Disconnect</Button>}
        </div>
      </div>
      <Tabs value={section} onChange={(s) => { setSection(s); }} items={[{ value: "config", label: "Brand & audience" }, { value: "niche", label: "Niche" },
        { value: "language", label: "Languages" }, { value: "video", label: "Video" }, { value: "publishing", label: "Publishing" }]} />
      <Form channel={channel} value={patch} onChange={setPatch} />
      <ErrorText error={save.error} />
      <div className="flex justify-end gap-2">
        {save.isSuccess && !Object.keys(patch).length && <span className="self-center text-sm text-emerald-600">Saved</span>}
        <Button disabled={!Object.keys(patch).length} loading={save.isPending} onClick={() => save.mutate(undefined, { onSuccess: () => setPatch({}) })}>Save changes</Button>
      </div>
    </Card>
  );
}
