import { fireEvent, screen, waitFor } from "@testing-library/react";
import { PublishDialog } from "@/components/publish-dialog";
import { QAReportView } from "@/components/qa-report";
import { mockFetch, renderWithQuery } from "./utils";

describe("approval workflow", () => {
  it("defaults to a private upload and sends the decision", async () => {
    const calls = mockFetch({ "/approvals/7/decide": { id: 7, status: "approved" } });
    const onClose = vi.fn();
    renderWithQuery(<PublishDialog approvalId={7} onClose={onClose} />);
    expect(screen.getByRole("combobox")).toHaveValue("private");
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(calls[0]).toMatchObject({ url: "/api/v1/approvals/7/decide", method: "POST", body: { approve: true, privacy: "private" } });
  });

  it("schedules a public release with an ISO timestamp", async () => {
    const calls = mockFetch({ "/approvals/3/decide": { id: 3 } });
    renderWithQuery(<PublishDialog approvalId={3} suggested="2030-01-01T12:30:00Z" onClose={() => {}} />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "schedule" } });
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].body).toMatchObject({ approve: true, privacy: "public", publish_at: "2030-01-01T12:30:00.000Z" });
  });

  it("can reject", async () => {
    const calls = mockFetch({ "/approvals/5/decide": { id: 5 } });
    renderWithQuery(<PublishDialog approvalId={5} onClose={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Reject video" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].body).toMatchObject({ approve: false });
  });
});

describe("QA report", () => {
  it("highlights critical failures", () => {
    renderWithQuery(<QAReportView report={{ score: 72, min_score: 85, passed: false, checks: {
      aspect_ratio: { passed: false, critical: true, detail: "1920x1080 (expected 9:16)", score: 0 },
      loudness: { passed: true, critical: false, detail: "-14 LUFS", score: 7 },
    } }} />);
    expect(screen.getByText("failed")).toBeInTheDocument();
    expect(screen.getByText("critical")).toBeInTheDocument();
    expect(screen.getByText(/expected 9:16/)).toBeInTheDocument();
  });
});
