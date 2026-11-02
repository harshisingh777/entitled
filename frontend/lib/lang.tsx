"use client";

import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import type { Text2 } from "./api";

type Lang = "hi" | "en";
type LangContext = { lang: Lang; toggle: () => void; t: (hi: string, en: string) => string; L: (text: Text2) => string };

const Context = createContext<LangContext | null>(null);

export function readPref(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writePref(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Private windows can refuse storage. The preference simply will not persist.
  }
}

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<Lang>("en");

  useEffect(() => {
    if (readPref("entitled.language") === "hi") setLang("hi");
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
    writePref("entitled.language", lang);
  }, [lang]);

  const toggle = useCallback(() => setLang((current) => (current === "hi" ? "en" : "hi")), []);
  const t = useCallback((hi: string, en: string) => (lang === "hi" ? hi : en), [lang]);
  const L = useCallback((text: Text2) => text[lang], [lang]);
  return <Context.Provider value={{ lang, toggle, t, L }}>{children}</Context.Provider>;
}

export function useLang(): LangContext {
  const value = useContext(Context);
  if (!value) throw new Error("useLang must sit inside LangProvider");
  return value;
}
