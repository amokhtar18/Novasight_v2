/**
 * UploadScreen — connect data: upload a CSV (or reopen a previous dataset).
 *
 * Polished for first-run, non-technical users (Task 6.5):
 *   - a short "How it works" guide sets expectations;
 *   - drag-and-drop + click upload, with client-side CSV validation that fails
 *     fast with a friendly message (before any network call);
 *   - previously-uploaded datasets are listed so returning users can jump
 *     straight back in instead of re-uploading.
 *
 * On success (upload or reopen) the dataset id goes into Zustand and the app
 * switches to ResultsScreen.
 */

import { useRef, useState } from "react";
import { Upload, Database, FileSpreadsheet, MessageSquareText, BarChart3 } from "lucide-react";

import { useDatasets, useUploadDataset } from "@/api/hooks";
import { useAppStore } from "@/store/appStore";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Label } from "@/components/ui/label";
import { EmptyState } from "@/components/ui/empty-state";

/** Accept only CSVs: by extension or MIME type (browsers vary on the latter). */
function isCsvFile(file: File): boolean {
  return file.name.toLowerCase().endsWith(".csv") || file.type === "text/csv";
}

const STEPS = [
  { icon: FileSpreadsheet, label: "Upload a CSV" },
  { icon: MessageSquareText, label: "Ask a question (or pick a column)" },
  { icon: BarChart3, label: "Get a chart instantly" },
];

export function UploadScreen() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const setSelectedDataset = useAppStore((s) => s.setSelectedDataset);

  const { mutate, isPending, isError, error } = useUploadDataset();
  const { data: datasets } = useDatasets();

  /** Validate + accept a chosen file (from picker or drop). */
  function acceptFile(file: File | null) {
    if (!file) return;
    if (!isCsvFile(file)) {
      setSelectedFile(null);
      setValidationError(`"${file.name}" is not a CSV file. Please choose a .csv file.`);
      return;
    }
    setValidationError(null);
    setSelectedFile(file);
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    acceptFile(e.target.files?.[0] ?? null);
  }

  function handleDrop(e: React.DragEvent<HTMLButtonElement>) {
    e.preventDefault();
    setIsDragging(false);
    acceptFile(e.dataTransfer.files?.[0] ?? null);
  }

  function handleUpload() {
    if (!selectedFile) return;
    mutate(selectedFile, {
      onSuccess: (dataset) => setSelectedDataset(dataset.id),
    });
  }

  const hasDatasets = datasets !== undefined && datasets.length > 0;

  return (
    <div className="flex min-h-screen items-start justify-center bg-background p-4">
      <div className="w-full max-w-xl space-y-4 py-8">
        <div className="space-y-1 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">Analytica</h1>
          <p className="text-sm text-muted-foreground">
            Turn a spreadsheet into charts and answers — no SQL required.
          </p>
        </div>

        {/* How it works */}
        <ol className="grid grid-cols-3 gap-2" aria-label="How it works">
          {STEPS.map((step, i) => (
            <li
              key={step.label}
              className="flex flex-col items-center gap-2 rounded-lg border bg-card p-3 text-center"
            >
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                {i + 1}
              </span>
              <step.icon className="h-5 w-5 text-muted-foreground" aria-hidden />
              <span className="text-xs text-muted-foreground">{step.label}</span>
            </li>
          ))}
        </ol>

        {/* Upload card */}
        <Card>
          <CardHeader>
            <CardTitle>Upload a CSV</CardTitle>
            <CardDescription>
              Drag a file here or click to browse. Your first chart appears right after.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <input
              ref={fileInputRef}
              id="csv-file"
              type="file"
              accept=".csv,text/csv"
              className="sr-only"
              onChange={handleFileChange}
              aria-label="Select CSV file"
            />

            <div className="space-y-1">
              <Label htmlFor="csv-file">CSV file</Label>
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                onDragOver={(e) => {
                  e.preventDefault();
                  setIsDragging(true);
                }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={handleDrop}
                className={`w-full rounded-md border-2 border-dashed p-6 text-center text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                  isDragging
                    ? "border-primary bg-primary/5 text-primary"
                    : "border-muted-foreground/40 text-muted-foreground hover:border-primary hover:text-primary"
                }`}
                aria-controls="csv-file"
              >
                {selectedFile ? (
                  <span className="font-medium text-foreground">
                    {selectedFile.name}{" "}
                    <span className="text-muted-foreground">
                      ({(selectedFile.size / 1024).toFixed(1)} KB)
                    </span>
                  </span>
                ) : (
                  <span className="flex flex-col items-center gap-2">
                    <Upload className="h-8 w-8" aria-hidden />
                    {isDragging ? "Drop your CSV to upload" : "Drag & drop a CSV, or click to browse"}
                  </span>
                )}
              </button>
            </div>

            {validationError && (
              <Alert variant="destructive" role="alert">
                <AlertTitle>Unsupported file</AlertTitle>
                <AlertDescription>{validationError}</AlertDescription>
              </Alert>
            )}

            {isError && (
              <Alert variant="destructive">
                <AlertTitle>Upload failed</AlertTitle>
                <AlertDescription>
                  {error instanceof Error ? error.message : "An unexpected error occurred."}
                </AlertDescription>
              </Alert>
            )}

            <Button
              onClick={handleUpload}
              disabled={!selectedFile || isPending}
              className="w-full"
            >
              {isPending ? "Uploading…" : "Upload and analyse"}
            </Button>
          </CardContent>
        </Card>

        {/* Previously uploaded datasets — reopen without re-uploading. */}
        {hasDatasets && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Database className="h-4 w-4" aria-hidden />
                Your datasets
              </CardTitle>
              <CardDescription>Pick up where you left off.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              <ul className="divide-y rounded-md border">
                {datasets.map((d) => (
                  <li key={d.id} className="flex items-center justify-between gap-3 p-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{d.name}</p>
                      <p className="truncate text-xs text-muted-foreground">
                        {d.original_filename}
                      </p>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setSelectedDataset(d.id)}
                      aria-label={`Open ${d.name}`}
                    >
                      Open
                    </Button>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}

        {datasets !== undefined && !hasDatasets && (
          <EmptyState
            icon={<Database className="h-6 w-6" />}
            title="No datasets yet"
            description="Upload your first CSV above to get started."
          />
        )}
      </div>
    </div>
  );
}
