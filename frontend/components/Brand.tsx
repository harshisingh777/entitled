"use client";

import Link from "next/link";

export function Brand() {
  return (
    <Link href="/" className="brand" aria-label="Entitled">
      <span className="brand-mark" aria-hidden="true">E</span>
      <span className="brand-word">Entitled</span>
    </Link>
  );
}
