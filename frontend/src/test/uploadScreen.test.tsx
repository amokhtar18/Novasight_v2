/**
 * Tests for the polished UploadScreen (Task 6.5):
 *   (a) onboarding "How it works" guide is shown;
 *   (b) non-CSV files are rejected client-side with a friendly message;
 *   (c) a valid CSV is accepted and enables the upload button;
 *   (d) previously-uploaded datasets are listed and "Open" selects one.
 *
 * API hooks are mocked; the real Zustand store is used and reset per test.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { UploadScreen } from "@/screens/UploadScreen";
import { useAppStore } from "@/store/appStore";
import type { DatasetRead } from "@/types/api";

vi.mock("@/api/hooks", () => ({
  useUploadDataset: vi.fn(),
  useDatasets: vi.fn(),
}));

import { useUploadDataset, useDatasets } from "@/api/hooks";

const mockUpload = vi.mocked(useUploadDataset);
const mockDatasets = vi.mocked(useDatasets);

function uploadReturn(overrides: Partial<ReturnType<typeof useUploadDataset>> = {}) {
  return {
    mutate: vi.fn(),
    isPending: false,
    isError: false,
    error: null,
    ...overrides,
  } as unknown as ReturnType<typeof useUploadDataset>;
}

function datasetsReturn(data: DatasetRead[] | undefined) {
  return { data } as unknown as ReturnType<typeof useDatasets>;
}

const sampleDataset: DatasetRead = {
  id: "ds-123",
  name: "Sales",
  original_filename: "sales.csv",
  content_type: "text/csv",
  size_bytes: 100,
  status: "ready",
  created_at: "2026-01-01T00:00:00Z",
};

beforeEach(() => {
  mockUpload.mockReturnValue(uploadReturn());
  mockDatasets.mockReturnValue(datasetsReturn([]));
  useAppStore.getState().reset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("UploadScreen — onboarding", () => {
  it("(a) shows the How it works guide", () => {
    render(<UploadScreen />);
    const guide = screen.getByRole("list", { name: /how it works/i });
    expect(guide).toBeInTheDocument();
    // Assert the unique step labels (avoids matching the card title "Upload a CSV").
    expect(screen.getByText(/ask a question/i)).toBeInTheDocument();
    expect(screen.getByText(/get a chart/i)).toBeInTheDocument();
  });
});

describe("UploadScreen — client-side CSV validation", () => {
  it("(b) rejects a non-CSV file with a friendly message and keeps upload disabled", () => {
    render(<UploadScreen />);
    const input = screen.getByLabelText(/select csv file/i);
    const txt = new File(["hello"], "notes.txt", { type: "text/plain" });
    fireEvent.change(input, { target: { files: [txt] } });

    expect(screen.getByText(/is not a csv file/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /upload and analyse/i })).toBeDisabled();
  });

  it("(c) accepts a valid CSV and enables the upload button", () => {
    render(<UploadScreen />);
    const input = screen.getByLabelText(/select csv file/i);
    const csv = new File(["a,b\n1,2"], "data.csv", { type: "text/csv" });
    fireEvent.change(input, { target: { files: [csv] } });

    expect(screen.getByText(/data\.csv/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /upload and analyse/i })).not.toBeDisabled();
  });
});

describe("UploadScreen — drag and drop", () => {
  it("accepts a valid CSV dropped on the dropzone", () => {
    render(<UploadScreen />);
    const dropzone = screen.getByRole("button", { name: /drag & drop a csv/i });
    const csv = new File(["a,b\n1,2"], "dropped.csv", { type: "text/csv" });
    fireEvent.drop(dropzone, { dataTransfer: { files: [csv] } });

    expect(screen.getByText(/dropped\.csv/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /upload and analyse/i })).not.toBeDisabled();
  });

  it("rejects a non-CSV dropped file with a friendly message", () => {
    render(<UploadScreen />);
    const dropzone = screen.getByRole("button", { name: /drag & drop a csv/i });
    const txt = new File(["x"], "notes.txt", { type: "text/plain" });
    fireEvent.drop(dropzone, { dataTransfer: { files: [txt] } });

    expect(screen.getByText(/is not a csv file/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /upload and analyse/i })).toBeDisabled();
  });
});

describe("UploadScreen — previous datasets", () => {
  it("(d) lists datasets and Open selects one in the store", () => {
    mockDatasets.mockReturnValue(datasetsReturn([sampleDataset]));
    render(<UploadScreen />);

    expect(screen.getByText("Sales")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /open/i }));

    expect(useAppStore.getState().selectedDatasetId).toBe("ds-123");
  });

  it("shows an empty state when there are no datasets", () => {
    mockDatasets.mockReturnValue(datasetsReturn([]));
    render(<UploadScreen />);
    expect(screen.getByText(/no datasets yet/i)).toBeInTheDocument();
  });
});
