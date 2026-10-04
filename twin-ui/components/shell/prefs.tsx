"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

interface Prefs {
  anonymous: boolean;
  setAnonymous: (v: boolean) => void;
}

const PrefsContext = createContext<Prefs>({ anonymous: false, setAnonymous: () => {} });
const KEY = "twin:anonymous";

/** Per-viewer display preferences (browser storage; a convenience, never data). */
export function PrefsProvider({ children }: { children: ReactNode }) {
  const [anonymous, setAnon] = useState(false);
  useEffect(() => {
    try {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- read once after hydration
      setAnon(localStorage.getItem(KEY) === "1");
    } catch {}
  }, []);
  const setAnonymous = (v: boolean) => {
    setAnon(v);
    try {
      localStorage.setItem(KEY, v ? "1" : "0");
    } catch {}
  };
  return <PrefsContext value={{ anonymous, setAnonymous }}>{children}</PrefsContext>;
}

export const usePrefs = () => useContext(PrefsContext);
