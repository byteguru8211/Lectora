import { createContext, useContext } from "react";

export interface UiActions {
  openUpload: (mode?: "file" | "url") => void;
  openPalette: () => void;
}

const UiContext = createContext<UiActions>({
  openUpload: () => undefined,
  openPalette: () => undefined,
});

export const UiProvider = UiContext.Provider;

export function useUi(): UiActions {
  return useContext(UiContext);
}
