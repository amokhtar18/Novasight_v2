/**
 * UploadCard — drag-and-drop CSV upload with client-side validation.
 *
 * Self-contained: validates the file is a CSV before any network call, uploads
 * via the useUploadDataset mutation, and calls `onUploaded` with the created
 * dataset on success. Used by the Data sources page (and the Overview quick
 * action). Extracted from the original UploadScreen so the logic has one home.
 */

import { useRef, useState } from "react";
import { Upload } from "lucide-react";

import { useUploadDataset } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/cn";
import { formatBytes } from "@/lib/format";
import type { DatasetRead } from "@/types/api";

/** Accept only CSVs: by extension or MIME type (browsers vary on the latter). */
export function isCsvFile(file: File): boolean {
  return file.name.toLowerCase().endsWith(".csv") || file.type === "text/csv";
}

interface UploadCardProps {
  onUploaded?: (dataset: DatasetRead) => void;
}

export function UploadCard({ onUploaded }: UploadCardProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  const { mutate, isPending, isError, error } = useUploadDataset();

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

  function handleUpload() {
    if (!selectedFile) return;
    mutate(selectedFile, {
      onSuccess: (dataset) => {
        setSelectedFile(null);
        onUploaded?.(dataset);
      },
    });
  }

  return (
    <div className="space-y-4">
      <input
        ref={fileInputRef}
        id="csv-file"
        type="file"
        accept=".csv,text/csv"
        className="sr-only"
        onChange={(e) => acceptFile(e.target.files?.[0] ?? null)}
        aria-label="Select CSV file"
      />

      <div className="space-y-1.5">
        <Label htmlFor="csv-file">CSV file</Label>
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setIsDragging(false);
            acceptFile(e.dataTransfer.files?.[0] ?? null);
          }}
          className={cn(
            "flex w-full flex-col items-center gap-2 rounded-xl border-2 border-dashed p-8 text-center text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            isDragging
              ? "border-primary bg-primary/5 text-primary"
              : "border-border text-muted-foreground hover:border-primary/60 hover:text-foreground"
          )}
          aria-controls="csv-file"
        >
          {selectedFile ? (
            <span className="font-medium text-foreground">
              {selectedFile.name}{" "}
              <span className="text-muted-foreground">
                ({formatBytes(selectedFile.size)})
              </span>
            </span>
          ) : (
            <>
              <span className="flex h-11 w-11 items-center justify-center rounded-full bg-primary/10">
                <Upload className="h-5 w-5 text-primary" aria-hidden />
              </span>
              {isDragging ? "Drop your CSV to upload" : "Drag & drop a CSV, or click to browse"}
            </>
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

      <Button onClick={handleUpload} disabled={!selectedFile || isPending} className="w-full">
        {isPending ? "Uploading…" : "Upload and analyse"}
      </Button>
    </div>
  );
}
