/**
 * App root — thin shell that switches between Upload and Results screens
 * based on Zustand state (no router needed for this thin slice).
 */

import { useAppStore } from "@/store/appStore";
import { UploadScreen } from "@/screens/UploadScreen";
import { ResultsScreen } from "@/screens/ResultsScreen";

export function App() {
  const selectedDatasetId = useAppStore((s) => s.selectedDatasetId);

  return selectedDatasetId ? <ResultsScreen /> : <UploadScreen />;
}
