"use client";
import { AlertTriangle, Baby, Plus, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, Button, Field, Input, Select, Switch, Textarea, cn } from "@/components/ui";
import { useCatalog } from "@/hooks/use-api";
import { api } from "@/services/api";
import type { Channel, ChannelSettings } from "@/types";

export type ChannelPatch = {
  title?: string; description?: string; settings?: Partial<ChannelSettings>;
  brand?: Partial<Channel["brand"]>; niches?: string[]; custom_niches?: { name: string; keywords: string[] }[];
};

const COUNTRIES = [["IN", "India"], ["US", "United States"], ["GB", "United Kingdom"], ["CA", "Canada"], ["AU", "Australia"],
  ["AE", "UAE"], ["SA", "Saudi Arabia"], ["ES", "Spain"], ["MX", "Mexico"], ["FR", "France"], ["BD", "Bangladesh"], ["PK", "Pakistan"]];
const STYLES = ["educational", "storytelling", "documentary", "entertaining", "news_analysis", "motivational", "kids_friendly"];
const VISUALS = [["motion_graphics", "Motion graphics"], ["animation", "Animation"], ["cartoon", "Cartoon animation"],
  ["realistic", "Realistic visuals"], ["documentary", "Documentary style"], ["infographic", "Educational / infographic"]];
const VOICES = [["female_warm", "Female · warm"], ["male_calm", "Male · calm"], ["female_energetic", "Female · energetic"],
  ["male_energetic", "Male · energetic"], ["child_friendly", "Child-friendly"]];

/** Channel identity + audience + brand (onboarding step 3). */
export function ChannelConfigForm({ channel, value, onChange }: { channel: Channel; value: ChannelPatch; onChange: (p: ChannelPatch) => void }) {
  const s = { ...channel.settings, ...value.settings };
  const b = { ...channel.brand, ...value.brand };
  const set = (k: keyof ChannelSettings, v: unknown) => onChange({ ...value, settings: { ...value.settings, [k]: v } });
  const setB = (k: string, v: string) => onChange({ ...value, brand: { ...value.brand, [k]: v } });
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Field label="Channel name"><Input value={value.title ?? channel.title} onChange={(e) => onChange({ ...value, title: e.target.value })} /></Field>
      <Field label="Target country">
        <Select value={s.target_country} onChange={(e) => set("target_country", e.target.value)}>
          {COUNTRIES.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
        </Select>
      </Field>
      <div className="md:col-span-2">
        <Field label="Channel description"><Textarea rows={3} value={value.description ?? channel.description} onChange={(e) => onChange({ ...value, description: e.target.value })} /></Field>
      </div>
      <Field label="Primary audience" hint="e.g. 'Indian college students interested in tech'">
        <Input value={s.primary_audience} onChange={(e) => set("primary_audience", e.target.value)} />
      </Field>
      <Field label="Content style">
        <Select value={s.content_style} onChange={(e) => set("content_style", e.target.value)}>
          {STYLES.map((x) => <option key={x} value={x}>{x.replace("_", " ")}</option>)}
        </Select>
      </Field>
      <Field label="Brand name"><Input value={b.brand_name} onChange={(e) => setB("brand_name", e.target.value)} /></Field>
      <Field label="Tagline"><Input value={b.tagline} onChange={(e) => setB("tagline", e.target.value)} /></Field>
      <Field label="Primary colour"><Input type="color" value={b.primary_color} onChange={(e) => setB("primary_color", e.target.value)} /></Field>
      <Field label="Accent colour"><Input type="color" value={b.secondary_color} onChange={(e) => setB("secondary_color", e.target.value)} /></Field>
      <div className="md:col-span-2">
        <Field label="Brand identity" hint="Tone of voice, personality, what makes this channel different.">
          <Textarea rows={2} value={b.brand_identity} onChange={(e) => setB("brand_identity", e.target.value)} />
        </Field>
      </div>
      <BrandUpload channel={channel} asset="logo" />
      <BrandUpload channel={channel} asset="banner" />
    </div>
  );
}

function BrandUpload({ channel, asset }: { channel: Channel; asset: "logo" | "banner" }) {
  const [state, setState] = useState<string>(channel.brand[`${asset}_path`] ? "uploaded" : "");
  return (
    <Field label={asset === "logo" ? "Logo (PNG/JPG)" : "Banner (PNG/JPG)"} hint="Stored with the channel; upload it to YouTube Studio yourself — the API can't change channel art.">
      <Input type="file" accept="image/png,image/jpeg,image/webp" onChange={async (e) => {
        const f = e.target.files?.[0];
        if (!f) return;
        const fd = new FormData();
        fd.append("file", f);
        setState("uploading…");
        try {
          await api.upload(`/channels/${channel.id}/brand/${asset}`, fd);
          setState("uploaded");
        } catch (err) {
          setState(err instanceof Error ? err.message : "failed");
        }
      }} />
      {state && <span className="text-xs text-muted-foreground">{state}</span>}
    </Field>
  );
}

/** Niche multi-select with custom niches (onboarding step 4). */
export function NicheForm({ channel, value, onChange }: { channel: Channel; value: ChannelPatch; onChange: (p: ChannelPatch) => void }) {
  const cat = useCatalog();
  const selected = value.niches ?? channel.niches.filter((n) => !n.is_custom).map((n) => n.slug);
  const custom = value.custom_niches ?? channel.niches.filter((n) => n.is_custom).map((n) => ({ name: n.name, keywords: n.keywords }));
  const [newName, setNewName] = useState("");
  const [newKw, setNewKw] = useState("");
  const toggle = (slug: string) =>
    onChange({ ...value, niches: selected.includes(slug) ? selected.filter((s) => s !== slug) : [...selected, slug], custom_niches: custom });
  const kids = cat.data?.niches.filter((n) => selected.includes(n.slug) && n.kids) ?? [];
  const total = selected.length + custom.length;
  return (
    <div className="space-y-4">
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {cat.data?.niches.map((n) => (
          <button key={n.slug} type="button" onClick={() => toggle(n.slug)}
            className={cn("flex items-center justify-between rounded-md border px-3 py-2 text-left text-sm",
              selected.includes(n.slug) ? "border-primary bg-primary/10" : "border-border hover:bg-muted")}>
            {n.name}
            {n.kids && <Baby className="h-4 w-4 text-muted-foreground" />}
          </button>
        ))}
      </div>
      <div className="rounded-md border border-border p-3">
        <p className="mb-2 text-sm font-medium">Custom niche</p>
        <div className="flex flex-wrap gap-2">
          <Input className="max-w-xs" placeholder="Niche name, e.g. Indian Railways" value={newName} onChange={(e) => setNewName(e.target.value)} />
          <Input className="max-w-xs" placeholder="keywords, comma separated" value={newKw} onChange={(e) => setNewKw(e.target.value)} />
          <Button type="button" variant="outline" disabled={!newName.trim()} onClick={() => {
            onChange({ ...value, niches: selected, custom_niches: [...custom, { name: newName.trim(), keywords: newKw.split(",").map((k) => k.trim()).filter(Boolean) }] });
            setNewName(""); setNewKw("");
          }}><Plus className="h-4 w-4" /> Add</Button>
        </div>
        <div className="mt-2 flex flex-wrap gap-2">
          {custom.map((c, i) => (
            <Badge key={i} tone="violet">{c.name}
              <button className="ml-1" aria-label={`remove ${c.name}`} onClick={() => onChange({ ...value, niches: selected, custom_niches: custom.filter((_, j) => j !== i) })}><X className="h-3 w-3" /></button>
            </Badge>
          ))}
        </div>
      </div>
      {total > 1 && (
        <p className="flex items-start gap-2 rounded-md bg-amber-50 p-3 text-sm text-amber-800 dark:bg-amber-900/30 dark:text-amber-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          We recommend one coherent niche per channel. Mixing unrelated topics confuses YouTube&apos;s recommendations and your audience — consider a separate channel per niche.
        </p>
      )}
      {kids.length > 0 && (
        <p className="flex items-start gap-2 rounded-md bg-blue-50 p-3 text-sm text-blue-800 dark:bg-blue-900/30 dark:text-blue-200">
          <Baby className="mt-0.5 h-4 w-4 shrink-0" />
          Children&apos;s content: videos will be marked <b>Made for Kids</b> (required by COPPA / YouTube policy). Comments and personalised ads are disabled by YouTube,
          scripts are screened for child-safety, and only original characters are used.
        </p>
      )}
    </div>
  );
}

/** Languages (onboarding step 5). */
export function LanguageForm({ channel, value, onChange }: { channel: Channel; value: ChannelPatch; onChange: (p: ChannelPatch) => void }) {
  const cat = useCatalog();
  const s = { ...channel.settings, ...value.settings };
  const set = (k: keyof ChannelSettings, v: unknown) => onChange({ ...value, settings: { ...value.settings, [k]: v } });
  const langs = Object.entries(cat.data?.languages ?? {});
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Field label="Original (script) language">
        <Select value={s.language} onChange={(e) => onChange({ ...value, settings: { ...value.settings, language: e.target.value, voiceover_language: e.target.value } })}>
          {langs.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </Select>
      </Field>
      <Field label="Voiceover language" hint="Free system voices cover most languages via espeak-ng; quality varies.">
        <Select value={s.voiceover_language} onChange={(e) => set("voiceover_language", e.target.value)}>
          {langs.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </Select>
      </Field>
      <div className="md:col-span-2">
        <Label2>Subtitle languages</Label2>
        <div className="flex flex-wrap gap-2">
          {langs.map(([k, v]) => {
            const on = s.subtitle_languages.includes(k);
            return (
              <button key={k} type="button" onClick={() => set("subtitle_languages", on ? s.subtitle_languages.filter((x) => x !== k) : [...s.subtitle_languages, k])}
                className={cn("rounded-full border px-3 py-1 text-xs", on ? "border-primary bg-primary/10" : "border-border")}>{v}</button>
            );
          })}
        </div>
        <p className="mt-1 text-xs text-muted-foreground">Subtitles are generated in the script language. Translated versions use the same pipeline with a new script language.</p>
      </div>
    </div>
  );
}

function Label2({ children }: { children: React.ReactNode }) {
  return <p className="mb-1 text-xs font-medium text-muted-foreground">{children}</p>;
}

/** Video format/style (onboarding step 6). */
export function VideoForm({ channel, value, onChange }: { channel: Channel; value: ChannelPatch; onChange: (p: ChannelPatch) => void }) {
  const cat = useCatalog();
  const s = { ...channel.settings, ...value.settings };
  const set = (k: keyof ChannelSettings, v: unknown) => onChange({ ...value, settings: { ...value.settings, [k]: v } });
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Field label="Shorts length" hint="Shorts are 9:16 vertical. Up to 3 minutes is allowed for eligible channels.">
        <Select value={s.short_duration_seconds} onChange={(e) => set("short_duration_seconds", Number(e.target.value))}>
          {cat.data?.short_durations.map((d) => <option key={d} value={d}>{d < 180 ? `${d} seconds` : "Up to 3 minutes"}</option>)}
        </Select>
      </Field>
      <Field label="Long-form length" hint="Long-form videos are 16:9 horizontal.">
        <Select value={s.long_duration_range} onChange={(e) => set("long_duration_range", e.target.value)}>
          {cat.data?.long_ranges.map((r) => <option key={r} value={r}>{r} minutes</option>)}
        </Select>
      </Field>
      <Field label="Visual style">
        <Select value={s.visual_style} onChange={(e) => set("visual_style", e.target.value)}>
          {VISUALS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </Select>
      </Field>
      <Field label="Voice style">
        <Select value={s.voice_style} onChange={(e) => set("voice_style", e.target.value)}>
          {VOICES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </Select>
      </Field>
      <Field label="Video quality">
        <Select value={s.video_quality} onChange={(e) => set("video_quality", e.target.value)}>
          <option value="1080p">1080p (recommended)</option>
          <option value="720p">720p (faster rendering)</option>
        </Select>
      </Field>
      <div className="flex flex-col justify-end gap-2">
        <Switch checked={s.background_music} onChange={(v) => set("background_music", v)} label="Background music (original, generated)" />
        <Switch checked={s.burn_subtitles} onChange={(v) => set("burn_subtitles", v)} label="Burned-in captions" />
      </div>
    </div>
  );
}

/** Publishing schedule and approval mode (onboarding step 7). */
export function PublishingForm({ channel, value, onChange }: { channel: Channel; value: ChannelPatch; onChange: (p: ChannelPatch) => void }) {
  const s = { ...channel.settings, ...value.settings };
  const set = (patch: Partial<ChannelSettings>) => onChange({ ...value, settings: { ...value.settings, ...patch } });
  const [time, setTime] = useState("12:00");
  const [zones, setZones] = useState<string[]>([]);
  useEffect(() => {
    try {
      setZones((Intl as unknown as { supportedValuesOf: (k: string) => string[] }).supportedValuesOf("timeZone"));
    } catch {
      setZones(["UTC", "Asia/Kolkata", "America/New_York", "Europe/London"]);
    }
  }, []);
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Field label="Shorts per day"><Input type="number" min={0} max={10} value={s.shorts_per_day} onChange={(e) => set({ shorts_per_day: Number(e.target.value) })} /></Field>
      <Field label="Long-form videos per week"><Input type="number" min={0} max={14} value={s.long_per_week} onChange={(e) => set({ long_per_week: Number(e.target.value) })} /></Field>
      <Field label="Preferred publishing times">
        <div className="flex flex-wrap items-center gap-2">
          {s.publish_times.map((t) => (
            <Badge key={t} tone="blue">{t}
              <button className="ml-1" aria-label={`remove ${t}`} onClick={() => set({ publish_times: s.publish_times.filter((x) => x !== t) })}><X className="h-3 w-3" /></button>
            </Badge>
          ))}
          <Input type="time" className="w-28" value={time} onChange={(e) => setTime(e.target.value)} />
          <Button type="button" size="sm" variant="outline" onClick={() => !s.publish_times.includes(time) && set({ publish_times: [...s.publish_times, time].sort() })}>Add</Button>
        </div>
      </Field>
      <Field label="Timezone">
        <Select value={s.timezone} onChange={(e) => set({ timezone: e.target.value })}>
          {(zones.length ? zones : [s.timezone]).map((z) => <option key={z} value={z}>{z}</option>)}
        </Select>
      </Field>
      <div className="space-y-3 md:col-span-2">
        <Switch checked={s.require_approval} onChange={(v) => set({ require_approval: v, auto_publish: v ? false : s.auto_publish })}
          label="Require my approval before anything is uploaded (recommended)" />
        <Switch checked={s.auto_publish} disabled={s.require_approval} onChange={(v) => set({ auto_publish: v })}
          label="Publish automatically at the scheduled times" />
        <p className="text-xs text-muted-foreground">
          Automatic public publishing also needs the global &quot;unattended publishing&quot; confirmation in Settings. Until then, every video waits for your approval.
        </p>
      </div>
    </div>
  );
}
