import { useCallback, useEffect, useMemo, useState } from "react";
import { Route, Routes, useLocation, useParams } from "react-router-dom";
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
import { PublicLibraryPage } from "./pages/PublicLibraryPage";
import { SharedLecturePage, SharedPage } from "./pages/SharedPage";
import { api } from "./api/client";

export default function App() {
  const auth = useAuth();
  const location = useLocation();
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

  if (location.pathname.startsWith("/shared/")) return <ToastProvider><Routes><Route path="/shared/videos/:token" element={<SharedLecturePage />} /><Route path="/shared/groups/:token" element={<SharedPage groupMode />} /><Route path="/shared/groups/:token/lectures/:lectureId" element={<SharedLecturePage groupMode />} /></Routes></ToastProvider>;
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
            <Route path="/public" element={<PublicLibraryPage />} />
            <Route path="/public/lectures/:lectureId" element={<PublicLectureRoute />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </AppShell>

        <UploadModal open={uploadOpen} onClose={() => setUploadOpen(false)} initialMode={uploadMode} />
        <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      </UiProvider>
    </ToastProvider>
  );
}

function PublicLectureRoute() {
  const { lectureId = "" } = useParams();

  useEffect(() => {
    if (!lectureId) return;
    const key = `lectora:public-view:${lectureId}`;
    if (sessionStorage.getItem(key)) return;
    sessionStorage.setItem(key, "1");
    api.recordPublicView(lectureId).catch(() => sessionStorage.removeItem(key));
  }, [lectureId]);

  return <LecturePage accessBase={`/api/public/lectures/${lectureId}`} backTo="/public" backLabel="Публичные видео" />;
}
