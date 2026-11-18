import { CheckCircle2, XCircle } from "lucide-react";
import { Badge } from "@/components/ui";
import type { QAReport } from "@/types";

export function QAReportView({ report }: { report: QAReport }) {
  return (
    <div className="mt-2 text-sm">
      <div className="mb-2 flex items-center gap-2">
        Score <b className="text-lg">{report.score}</b> / 100 (min {report.min_score})
        <Badge tone={report.passed ? "green" : "red"}>{report.passed ? "passed" : "failed"}</Badge>
      </div>
      <ul className="space-y-1">
        {Object.entries(report.checks ?? {}).map(([name, c]) => (
          <li key={name} className="flex gap-2">
            {c.passed ? <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" /> : <XCircle className="h-4 w-4 shrink-0 text-red-500" />}
            <span><b>{name.replace(/_/g, " ")}</b>{c.critical && !c.passed && <Badge tone="red" className="ml-1">critical</Badge>} — {c.detail}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
