/**
 * Tests for the extracted UploadCard:
 *   - non-CSV files are rejected client-side with a friendly message;
 *   - a valid CSV is accepted and enables the upload button;
 *   - drag-and-drop validates the same way.
 *
 * The upload hook is mocked — no network calls are made.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { UploadCard } from "@/components/data/UploadCard";

vi.mock("@/api/hooks", () => ({
  useUploadDataset: vi.fn(),
}));

import { useUploadDataset } from "@/api/hooks";

const mockUpload = vi.mocked(useUploadDataset);

function uploadReturn(overrides: Partial<ReturnType<typeof useUploadDataset>> = {}) {
  return {
    mutate: vi.fn(),
    isPending: false,
    isError: false,
    error: null,
    ...overrides,
  } as unknown as ReturnType<typeof useUploadDataset>;
}

beforeEach(() => {
  mockUpload.mockReturnValue(uploadReturn());
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("UploadCard — client-side CSV validation", () => {
  it("rejects a non-CSV file and keeps upload disabled", () => {
    render(<UploadCard />);
    const input = screen.getByLabelText(/select csv file/i);
    const txt = new File(["hello"], "notes.txt", { type: "text/plain" });
    fireEvent.change(input, { target: { files: [txt] } });

    expect(screen.getByText(/is not a csv file/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /upload and analyse/i })).toBeDisabled();
  });

  it("accepts a valid CSV and enables the upload button", () => {
    render(<UploadCard />);
    const input = screen.getByLabelText(/select csv file/i);
    const csv = new File(["a,b\n1,2"], "data.csv", { type: "text/csv" });
    fireEvent.change(input, { target: { files: [csv] } });

    expect(screen.getByText(/data\.csv/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /upload and analyse/i })).not.toBeDisabled();
  });
});

describe("UploadCard — drag and drop", () => {
  it("accepts a valid CSV dropped on the dropzone", () => {
    render(<UploadCard />);
    const dropzone = screen.getByRole("button", { name: /drag & drop a csv/i });
    const csv = new File(["a,b\n1,2"], "dropped.csv", { type: "text/csv" });
    fireEvent.drop(dropzone, { dataTransfer: { files: [csv] } });

    expect(screen.getByText(/dropped\.csv/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /upload and analyse/i })).not.toBeDisabled();
  });
});
