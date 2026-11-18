"use client";
import { Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Card, ErrorText, Field, Input } from "@/components/ui";
import { useApi } from "@/hooks/use-api";
import { api } from "@/services/api";
import type { User } from "@/types";

export default function LoginPage() {
  const router = useRouter();
  const status = useApi<{ needs_setup: boolean }>("/auth/status");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const setup = status.data?.needs_setup;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const user = await api.post<User>(setup ? "/auth/register" : "/auth/login", { email, password, name });
      router.replace(user.onboarding_completed ? "/dashboard" : "/onboarding");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <div className="mb-5 flex items-center gap-2 text-lg font-semibold"><Sparkles className="h-5 w-5 text-primary" /> AI YouTube Studio</div>
        <p className="mb-4 text-sm text-muted-foreground">
          {setup ? "Create the administrator account for this studio." : "Sign in to your studio."}
        </p>
        <form onSubmit={submit} className="space-y-3">
          {setup && <Field label="Your name"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>}
          <Field label="Email"><Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" /></Field>
          <Field label="Password" hint={setup ? "At least 8 characters." : undefined}>
            <Input type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)}
              autoComplete={setup ? "new-password" : "current-password"} />
          </Field>
          <ErrorText error={error} />
          <Button className="w-full" type="submit" loading={busy}>{setup ? "Create account" : "Sign in"}</Button>
        </form>
      </Card>
    </div>
  );
}
