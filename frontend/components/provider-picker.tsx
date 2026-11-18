"use client";
import { CheckCircle2, KeyRound, XCircle } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Input, cn } from "@/components/ui";
import { useAction, useApi, useCatalog } from "@/hooks/use-api";
import { api } from "@/services/api";
import type { Provider } from "@/types";

const KINDS = [["llm", "Research & scriptwriting (LLM)"], ["tts", "Voice"], ["image", "Images"], ["video", "AI video clips"]] as const;

export function ProviderPicker({ budgetMode, value, onChange }: { budgetMode: string; value: Record<string, string>; onChange: (v: Record<string, string>) => void }) {
  const provs = useApi<Provider[]>("/providers");
  const cat = useCatalog();
  const preset = cat.data?.budget_modes[budgetMode];
  return (
    <div className="space-y-5">
      {KINDS.map(([kind, label]) => {
        const list = (provs.data ?? []).filter((p) => p.kind === kind);
        const current = value[kind] ?? list.find((p) => p.is_default)?.name;
        return (
          <div key={kind}>
            <div className="mb-2 flex items-center justify-between text-sm font-medium">
              {label}
              {preset && <span className="text-xs text-muted-foreground">suggested for this budget: {preset[kind]}</span>}
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              {list.map((p) => (
                <ProviderCard key={p.id} p={p} selected={current === p.name} disabled={budgetMode === "free" && p.is_paid}
                  onSelect={() => onChange({ ...value, [kind]: p.name })} />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ProviderCard({ p, selected, disabled, onSelect }: { p: Provider; selected: boolean; disabled: boolean; onSelect: () => void }) {
  const [key, setKey] = useState("");
  const [url, setUrl] = useState(p.base_url ?? "");
  const save = useAction(() => api.patch(`/providers/${p.id}`, { ...(key ? { api_key: key } : {}), base_url: url, enabled: true }), ["/providers"]);
  const test = useAction(() => api.post(`/providers/${p.id}/test`), ["/providers"]);
  const needsUrl = ["ollama", "kokoro", "piper", "comfyui"].includes(p.name);
  return (
    <div className={cn("rounded-md border p-3 text-sm", selected ? "border-primary bg-primary/5" : "border-border", disabled && "opacity-50")}>
      <button className="flex w-full items-center justify-between text-left" disabled={disabled} onClick={onSelect}>
        <span className="font-medium">{p.display_name}</span>
        <span className="flex items-center gap-1">
          {p.is_paid ? <Badge tone="amber">paid</Badge> : <Badge tone="green">free</Badge>}
          {p.health_status === "ok" && <CheckCircle2 className="h-4 w-4 text-emerald-500" />}
          {p.health_status === "error" && <XCircle className="h-4 w-4 text-red-500" />}
        </span>
      </button>
      {selected && (p.needs_key || needsUrl) && (
        <div className="mt-2 space-y-2">
          {p.needs_key && (
            <div className="flex items-center gap-2">
              <KeyRound className="h-4 w-4 text-muted-foreground" />
              <Input type="password" autoComplete="off" placeholder={p.api_key_set ? `saved (${p.api_key_masked})` : "paste API key"} value={key}
                onChange={(e) => setKey(e.target.value)} />
            </div>
          )}
          {needsUrl && <Input placeholder="Base URL, e.g. http://localhost:11434" value={url} onChange={(e) => setUrl(e.target.value)} />}
          <div className="flex gap-2">
            <Button size="sm" variant="outline" loading={save.isPending} onClick={() => save.mutate(undefined, { onSuccess: () => setKey("") })}>Save</Button>
            <Button size="sm" variant="outline" loading={test.isPending} onClick={() => test.mutate(undefined)}>Test connection</Button>
          </div>
        </div>
      )}
      {p.health_message && <p className={cn("mt-1 text-xs", p.health_status === "error" ? "text-red-600" : "text-muted-foreground")}>{p.health_message}</p>}
    </div>
  );
}
