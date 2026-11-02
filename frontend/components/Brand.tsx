"use client";

import Link from "next/link";
import { Languages } from "lucide-react";
import { useLang } from "@/lib/lang";

export function Brand() {
  return (
    <Link href="/" className="brand" aria-label="Entitled">
      <span className="brand-mark" aria-hidden="true">E</span>
      <span className="brand-word">Entitled</span>
    </Link>
  );
}

export function LangToggle() {
  const { lang, toggle, t } = useLang();
  return (
    <button type="button" className="icon-btn with-label" onClick={toggle} aria-label={t("भाषा बदलें: English", "Switch language: Hindi")}>
      <Languages size={20} aria-hidden="true" />
      <span>{lang === "hi" ? "English" : "Hindi"}</span>
    </button>
  );
}
