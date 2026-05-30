"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import Shell from "../components/Shell";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Product = {
  id: string;
  name: string;
  ad_video_url: string | null;
  mind_target_url: string | null;
  qr_url?: string | null;
  created_at: string;
};

export default function ProductsPage() {
  const [items, setItems] = useState<Product[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API}/recognition/registered`)
      .then((r) => r.json())
      .then((data) => setItems(data))
      .catch((e) => setError(e?.message || "Failed to load"));
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((p) => p.name.toLowerCase().includes(q) || p.id.toLowerCase().includes(q));
  }, [items, query]);

  return (
    <Shell>
      <div className="flex flex-col gap-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="text-xs font-medium text-lime-300/90">Products</div>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight">Catalog</h1>
            <div className="mt-2 text-sm text-zinc-400">Generated videos + tracking targets</div>
          </div>
          <div className="flex gap-2">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search name or id..."
              className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm outline-none ring-lime-400/30 focus:ring-2 sm:w-72"
            />
            <Link
              href="/studio"
              className="inline-flex items-center justify-center rounded-lg bg-lime-400 px-4 py-2 text-sm font-semibold text-black transition hover:bg-lime-300"
            >
              New
            </Link>
          </div>
        </div>

        {error && <div className="text-sm text-red-300">{error}</div>}

        <div className="grid gap-3">
          {filtered.length === 0 ? (
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-8 text-center text-sm text-zinc-500">
              No products yet. Create one in Studio.
            </div>
          ) : (
            filtered.map((p) => (
              <div
                key={p.id}
                className="rounded-xl border border-white/10 bg-white/[0.03] p-4"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold text-white">{p.name}</div>
                    <div className="mt-1 truncate font-mono text-[11px] text-zinc-500">{p.id}</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span
                      className={[
                        "rounded-full px-2 py-1 text-[11px] font-semibold",
                        p.ad_video_url ? "bg-lime-400/10 text-lime-200 ring-1 ring-inset ring-lime-400/25" : "bg-white/5 text-zinc-400 ring-1 ring-inset ring-white/10",
                      ].join(" ")}
                    >
                      {p.ad_video_url ? "video" : "no video"}
                    </span>
                    <span
                      className={[
                        "rounded-full px-2 py-1 text-[11px] font-semibold",
                        p.mind_target_url ? "bg-lime-400/10 text-lime-200 ring-1 ring-inset ring-lime-400/25" : "bg-white/5 text-zinc-400 ring-1 ring-inset ring-white/10",
                      ].join(" ")}
                    >
                      {p.mind_target_url ? "tracking" : "no target"}
                    </span>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </Shell>
  );
}
