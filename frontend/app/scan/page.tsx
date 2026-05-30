"use client";

import { useEffect } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function ScanPage() {
  useEffect(() => {
    window.location.href = `${API}/static/scan.html`;
  }, []);

  return (
    <div className="fixed inset-0 flex items-center justify-center bg-[#050607]">
      <p className="text-sm text-zinc-400">Opening scanner…</p>
    </div>
  );
}
