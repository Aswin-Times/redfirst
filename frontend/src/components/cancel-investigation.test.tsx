import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CancelInvestigation } from "@/components/cancel-investigation";

afterEach(cleanup);

const open = () => fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

describe("CancelInvestigation", () => {
  it("does not cancel on the first click: it asks first", () => {
    const onConfirm = vi.fn();
    render(<CancelInvestigation onConfirm={onConfirm} busy={false} />);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    open();
    expect(screen.getByRole("alertdialog", { name: "Cancel this investigation?" })).toBeTruthy();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("says what cancelling means", () => {
    render(<CancelInvestigation onConfirm={vi.fn()} busy={false} />);
    open();
    expect(screen.getByRole("alertdialog").textContent).toMatch(/cannot be resumed/i);
    expect(screen.getByRole("alertdialog").textContent).toMatch(/stays in the report/i);
  });

  it("starts on the safe choice, so Enter does not cancel by accident", async () => {
    render(<CancelInvestigation onConfirm={vi.fn()} busy={false} />);
    open();
    const keep = await screen.findByRole("button", { name: "Keep running" });
    await waitFor(() => expect(document.activeElement).toBe(keep));
  });

  it("closes without cancelling on Keep running", async () => {
    const onConfirm = vi.fn();
    render(<CancelInvestigation onConfirm={onConfirm} busy={false} />);
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Keep running" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("closes without cancelling on Escape", async () => {
    const onConfirm = vi.fn();
    render(<CancelInvestigation onConfirm={onConfirm} busy={false} />);
    open();
    await screen.findByRole("alertdialog");
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("cancels once, and only, when confirmed", async () => {
    const onConfirm = vi.fn();
    render(<CancelInvestigation onConfirm={onConfirm} busy={false} />);
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Cancel investigation" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });

  it("shows progress and cannot be opened again while cancelling", () => {
    render(<CancelInvestigation onConfirm={vi.fn()} busy />);
    const trigger = screen.getByRole("button", { name: "Cancelling…" }) as HTMLButtonElement;
    expect(trigger.disabled).toBe(true);
  });
});
