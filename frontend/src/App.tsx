import { useCallback, useEffect, useMemo, useState } from "react";
import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { CommandPalette } from "./components/CommandPalette";
import { UploadModal } from "./components/UploadModal";
import { ToastProvider } from "./context/ToastContext";
import { UiProvider, type UiActions } from "./context/UiContext";
import { LibraryPage } from "./pages/LibraryPage";
import { LecturePage } from "./pages/LecturePage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { SearchPage } from "./pages/SearchPage";
import { AccountPage } from "./pages/AccountPage";
import { AuthPage } from "./pages/AuthPage";
import { useAuth } from "./context/AuthContext";

export default function App() {
  const auth = useAuth();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadMode, setUploadMode] = useState<"file" | "url">("file");

  const openUpload = useCallback((mode: "file" | "url" = "file") => {
    setUploadMode(mode);
    setUploadOpen(true);
  }, []);

  const openPalette = useCallback(() => setPaletteOpen(true), []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((current) => !current);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const ui = useMemo<UiActions>(() => ({ openUpload, openPalette }), [openUpload, openPalette]);

  if (auth.loading) return <div className="app-loader"><span className="spinner" /></div>;
  if (!auth.user) return <AuthPage />;

  return (
    <ToastProvider>
      <UiProvider value={ui}>
        <AppShell>
          <Routes>
            <Route path="/" element={<LibraryPage />} />
            <Route path="/lectures/:lectureId" element={<LecturePage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/account" element={<AccountPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </AppShell>

        <UploadModal open={uploadOpen} onClose={() => setUploadOpen(false)} initialMode={uploadMode} />
        <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      </UiProvider>
    </ToastProvider>
  );
}
