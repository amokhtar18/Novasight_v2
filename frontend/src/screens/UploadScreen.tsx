/**
 * UploadScreen — select and upload a CSV, then navigate to the results.
 *
 * Uses TanStack Query mutation (useUploadDataset) for the upload.
 * On success, stores the dataset id in Zustand and switches to ResultsScreen.
 */

import { useRef, useState } from "react";
import { Upload } from "lucide-react";

import { useUploadDataset } from "@/api/hooks";
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

export function UploadScreen() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const setSelectedDataset = useAppStore((s) => s.setSelectedDataset);

  const { mutate, isPending, isError, error } = useUploadDataset();

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0] ?? null;
    setSelectedFile(file);
  }

  function handleUpload() {
    if (!selectedFile) return;
    mutate(selectedFile, {
      onSuccess: (dataset) => {
        setSelectedDataset(dataset.id);
      },
    });
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Upload a CSV</CardTitle>
          <CardDescription>
            Select a CSV file to analyse. After upload you will see a chart of
            your data.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Hidden file input */}
          <input
            ref={fileInputRef}
            id="csv-file"
            type="file"
            accept=".csv,text/csv"
            className="sr-only"
            onChange={handleFileChange}
            aria-label="Select CSV file"
          />

          {/* Labelled click-target for the file input */}
          <div className="space-y-1">
            <Label htmlFor="csv-file">CSV file</Label>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="w-full rounded-md border-2 border-dashed border-muted-foreground/40 p-6 text-center text-sm text-muted-foreground hover:border-primary hover:text-primary transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
                  Click to select a CSV file
                </span>
              )}
            </button>
          </div>

          {isError && (
            <Alert variant="destructive">
              <AlertTitle>Upload failed</AlertTitle>
              <AlertDescription>
                {error instanceof Error
                  ? error.message
                  : "An unexpected error occurred."}
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
    </div>
  );
}
