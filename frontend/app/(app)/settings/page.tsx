"use client";
import { AlertTriangle } from "lucide-react";
import { useEffect, useState } from "react";
import { PageHeader } from "@/components/app-shell";
import { Button, Card, CardTitle, ErrorText, Field, Input, Select, Switch, Textarea } from "@/components/ui";
import { useAction, useApi, useCatalog, useMe } from "@/hooks/use-api";
import { api } from "@/services/api";
import type { AutomationSettings } from "@/types";

export default function SettingsPage() {
  const me = useMe();
  const cat = useCatalog();
  const s = useApi<AutomationSettings>("/settings");
  const [form, setForm] = useState<Partial<AutomationSettings>>({});
  const [blocklist, setBlocklist] = useState("");
  const [confirmUnattended, setConfirmUnattended] = useState(false);
  const save = useAction(() => api.patch("/settings", { ...form, trademark_blocklist: blocklist.split("\n").map((x) => x.trim()).filter(Boolean),
    confirm_unattended: confirmUnattended }), ["/settings", "/dashboard", "/automation"]);
  useEffect(() => { if (s.data) setBlocklist(s.data.trademark_blocklist.join("\n")); }, [s.data]);
  if (!s.data) return <PageHeader title="Settings" />;
  const v = { ...s.data, ...form };
  const set = <K extends keyof AutomationSettings>(k: K, val: AutomationSettings[K]) => setForm({ ...form, [k]: val });
  const readOnly = me.data?.role !== "admin";
  return (
    <>
      <PageHeader title="Settings" description="Global automation, budget, compliance and security settings." />
      <fieldset disabled={readOnly} className="grid gap-4 lg:grid-cols-2">
        <Card className="space-y-3">
          <CardTitle>Budget</CardTitle>
          <Field label="Mode">
            <Select value={v.budget_mode} onChange={(e) => set("budget_mode", e.target.value)}>
              {Object.entries(cat.data?.budget_modes ?? {}).map(([k, m]) => <option key={k} value={k}>{m.label}</option>)}
            </Select>
          </Field>
          <Field label="Monthly AI spending limit (USD)" hint="New paid generation pauses (with a notification) when reached. Raising it resumes paused runs.">
            <Input type="number" min={0} value={v.monthly_budget_usd} onChange={(e) => set("monthly_budget_usd", Number(e.target.value))} />
          </Field>
        </Card>
        <Card className="space-y-3">
          <CardTitle>Automation</CardTitle>
          <Field label="Trend scan interval (minutes)"><Input type="number" min={30} value={v.trend_scan_interval_minutes} onChange={(e) => set("trend_scan_interval_minutes", Number(e.target.value))} /></Field>
          <Field label="Analytics collection interval (hours)"><Input type="number" min={1} value={v.analytics_interval_hours} onChange={(e) => set("analytics_interval_hours", Number(e.target.value))} /></Field>
          <Switch checked={v.auto_select_topics} onChange={(x) => set("auto_select_topics", x)} label="Let the agent pick topics itself (otherwise only topics you approve are produced)" />
          <Field label="Minimum trend score for automatic topics"><Input type="number" min={0} max={100} value={v.min_trend_score} onChange={(e) => set("min_trend_score", Number(e.target.value))} /></Field>
        </Card>
        <Card className="space-y-3">
          <CardTitle>Quality & copyright</CardTitle>
          <Field label="Minimum quality score to publish" hint="Critical failures always block publishing regardless of score."><Input type="number" min={50} max={100} value={v.min_quality_score} onChange={(e) => set("min_quality_score", Number(e.target.value))} /></Field>
          <Field label="Maximum allowed text similarity (0–1)" hint="Share of phrases a script may share with any reference or source."><Input type="number" step={0.05} min={0.05} max={0.8} value={v.max_similarity} onChange={(e) => set("max_similarity", Number(e.target.value))} /></Field>
          <Field label="Extra protected names (one per line)" hint="Added to the built-in franchise/trademark list."><Textarea rows={4} value={blocklist} onChange={(e) => setBlocklist(e.target.value)} /></Field>
        </Card>
        <Card className="space-y-3">
          <CardTitle>Trend score weights</CardTitle>
          {Object.entries(v.trend_weights).map(([k, w]) => (
            <Field key={k} label={k.replace("_", " ")}>
              <Input type="number" step={0.05} min={0} value={w} onChange={(e) => set("trend_weights", { ...v.trend_weights, [k]: Number(e.target.value) })} />
            </Field>
          ))}
        </Card>
        <Card className="space-y-3 border-amber-300">
          <CardTitle className="flex items-center gap-2"><AlertTriangle className="h-4 w-4 text-amber-500" /> Unattended public publishing</CardTitle>
          <p className="text-sm text-muted-foreground">When on, channels with “publish automatically” and no approval requirement will release videos publicly at their scheduled times without asking you. Leave this off until you have reviewed several videos.</p>
          <Switch checked={v.unattended_publishing_enabled} onChange={(x) => set("unattended_publishing_enabled", x)} label="Allow unattended publishing" />
          {v.unattended_publishing_enabled && !s.data.unattended_publishing_enabled && (
            <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={confirmUnattended} onChange={(e) => setConfirmUnattended(e.target.checked)} className="mt-1" />
              I understand that videos will be published publicly on my channel without my review.</label>
          )}
        </Card>
        <Card className="space-y-3">
          <CardTitle>Data, notifications & security</CardTitle>
          <Field label="Keep intermediate files for (days)"><Input type="number" min={7} value={v.data_retention_days} onChange={(e) => set("data_retention_days", Number(e.target.value))} /></Field>
          <Switch checked={!!v.notification_prefs?.critical_only} onChange={(x) => set("notification_prefs", { ...v.notification_prefs, critical_only: x })} label="Only notify me about critical problems" />
          <p className="text-xs text-muted-foreground">Sessions use httpOnly cookies; OAuth tokens and API keys are encrypted at rest (Fernet); every change is written to the audit log. Use HTTPS in production (see docs/DEPLOYMENT.md).</p>
        </Card>
      </fieldset>
      <ErrorText error={save.error} />
      {!readOnly && (
        <div className="mt-4 flex justify-end gap-2">
          {save.isSuccess && <span className="self-center text-sm text-emerald-600">Saved</span>}
          <Button loading={save.isPending} onClick={() => save.mutate(undefined, { onSuccess: () => setForm({}) })}>Save settings</Button>
        </div>
      )}
    </>
  );
}
