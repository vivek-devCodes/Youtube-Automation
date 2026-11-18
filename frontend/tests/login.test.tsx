import { fireEvent, screen, waitFor } from "@testing-library/react";
import LoginPage from "@/app/login/page";
import { mockFetch, renderWithQuery } from "./utils";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push: vi.fn() }) }));

describe("authentication", () => {
  it("first run creates the admin account and goes to onboarding", async () => {
    const calls = mockFetch({ "/auth/status": { needs_setup: true }, "/auth/register": { id: 1, onboarding_completed: false } });
    renderWithQuery(<LoginPage />);
    await screen.findByText("Create the administrator account for this studio.");
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "me@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "longpassword" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/onboarding"));
    expect(calls.some((c) => c.url.endsWith("/auth/register"))).toBe(true);
  });

  it("shows server errors", async () => {
    mockFetch({ "/auth/status": { needs_setup: false } });
    renderWithQuery(<LoginPage />);
    await screen.findByText("Sign in to your studio.");
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "x@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "wrongpassword" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("not found")).toBeInTheDocument();
  });
});
