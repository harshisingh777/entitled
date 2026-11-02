"use client";

import { useEffect } from "react";

export default function ServiceWorker() {
  useEffect(() => {
    if (process.env.NODE_ENV === "production" && "serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        // The app works without it. Only offline shell caching is lost.
      });
    }
  }, []);
  return null;
}
