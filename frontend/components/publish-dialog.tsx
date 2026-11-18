"use client";
import { useState } from "react";
import { Button, Dialog, ErrorText, Field, Input, Select } from "@/components/ui";
import { useAction } from "@/hooks/use-api";
import { api } from "@/services/api";

/** Human approval of a video: choose privacy now, or schedule a public release. */
export function PublishDialog({ approvalId, suggested, onClose }: { approvalId: number; suggested?: string; onClose: () => void }) {
  const [mode, setMode] = useState<"private" | "unlisted" | "public" | "schedule">("private");
  const toLocal = (iso?: string) => (iso ? new Date(new Date(iso).getTime() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16) : "");
  const [when, setWhen] = useState(toLocal(suggested));
  const decide = useAction((approve: boolean) => api.post(`/approvals/${approvalId}/decide`, approve
    ? mode === "schedule" ? { approve, privacy: "public", publish_at: new Date(when).toISOString() } : { approve, privacy: mode }
    : { approve, note: "rejected in studio" }), ["/content", "/approvals", "/videos", "/dashboard", "/publishing"]);
  return (
    <Dialog open onClose={onClose} title="Approve video for YouTube">
      <div className="space-y-3 text-sm">
        <Field label="How should it go out?">
          <Select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
            <option value="private">Upload as private (safest — publish later in YouTube Studio)</option>
            <option value="unlisted">Upload as unlisted</option>
            <option value="public">Publish publicly now</option>
            <option value="schedule">Schedule public release</option>
          </Select>
        </Field>
        {mode === "schedule" && <Field label="Release time (your local time)"><Input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} /></Field>}
        <p className="text-xs text-muted-foreground">The upload sets the AI-content disclosure and audience (Made for Kids) flags. Success is shown only after YouTube confirms the upload.</p>
        <ErrorText error={decide.error} />
        <div className="flex justify-between gap-2">
          <Button variant="destructive" loading={decide.isPending && decide.variables === false} onClick={() => decide.mutate(false, { onSuccess: onClose })}>Reject video</Button>
          <div className="flex gap-2">
            <Button variant="outline" onClick={onClose}>Cancel</Button>
            <Button variant="success" disabled={mode === "schedule" && !when} loading={decide.isPending && decide.variables === true}
              onClick={() => decide.mutate(true, { onSuccess: onClose })}>Approve</Button>
          </div>
        </div>
      </div>
    </Dialog>
  );
}
