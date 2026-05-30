"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Shell from "../components/Shell";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type RegisteredProduct = {
  id: string;
  name: string;
  ad_video_url: string | null;
  mind_target_url: string | null;
  qr_url: string | null;
  created_at: string;
};

let _Compiler: any = null;
async function getMindARCompiler() {
  if (_Compiler) return _Compiler;
  const sources = [
    "https://cdn.jsdelivr.net/npm/mind-ar@1.2.5/dist/mindar-image.prod.js",
    "https://unpkg.com/mind-ar@1.2.5/dist/mindar-image.prod.js",
  ];
  let lastError: unknown = null;
  for (const url of sources) {
    try {
      const mod = await import(/* webpackIgnore: true */ (url as any));
      _Compiler = mod.Compiler;
      return _Compiler;
    } catch (e) {
      lastError = e;
    }
  }
  throw lastError;
}

async function compileMindTarget(imageFiles: File[], onProgress?: (p: number) => void): Promise<Blob> {
  const Compiler = await getMindARCompiler();
  const compiler = new Compiler();

  const images = await Promise.all(
    imageFiles.map(
      (f) =>
        new Promise<HTMLImageElement>((resolve, reject) => {
          const img = new Image();
          img.onload = () => resolve(img);
          img.onerror = () => reject(new Error("Failed to load image"));
          img.src = URL.createObjectURL(f);
        }),
    ),
  );

  await compiler.compileImageTargets(images, (p: number) => onProgress?.(p));
  const buffer = await compiler.exportData();
  return new Blob([buffer], { type: "application/octet-stream" });
}

export default function StudioPage() {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [images, setImages] = useState<File[]>([]);
  const [adVideo, setAdVideo] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mindARLoaded, setMindARLoaded] = useState(false);
  const [created, setCreated] = useState<RegisteredProduct | null>(null);
  const [compilePct, setCompilePct] = useState<number | null>(null);

  const imagesRef = useRef<HTMLInputElement>(null);
  const adVideoRef = useRef<HTMLInputElement>(null);

  const canSubmit = useMemo(() => {
    if (busy) return false;
    if (!name.trim()) return false;
    if (images.length < 2) return false;
    return true;
  }, [busy, name, images.length]);

  useEffect(() => {
    getMindARCompiler()
      .then(() => setMindARLoaded(true))
      .catch(() => setMindARLoaded(false));
  }, []);

  async function register() {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    setCreated(null);
    setCompilePct(null);

    try {
      const fd = new FormData();
      fd.append("name", name.trim());
      images.forEach((img) => fd.append("images", img));
      if (adVideo) fd.append("ad_video", adVideo);

      // MindAR compile is optional — scanner uses COCO-SSD + AKAZE, not MindAR
      if (mindARLoaded) {
        setStatus("Compiling AR tracking target...");
        try {
          const mindBlob = await compileMindTarget(images, (p) => setCompilePct(p));
          fd.append("mind_target", new File([mindBlob], "target.mind"));
        } catch {
          // non-fatal — skip .mind file if compile fails
        }
        setCompilePct(null);
      }

      setStatus("Uploading photos + registering product...");

      const res = await fetch(`${API}/recognition/register`, { method: "POST", body: fd });
      if (!res.ok) {
        let message = await res.text();
        try {
          const json = JSON.parse(message);
          message = json.detail || json.ErrMsg || message;
        } catch {}
        throw new Error(message);
      }

      const data = (await res.json()) as RegisteredProduct;
      setCreated(data);
      setStatus("Done");
    } catch (e: any) {
      setError(e.message || "Failed");
      setStatus(null);
    } finally {
      setBusy(false);
      setCompilePct(null);
    }
  }

  function reset() {
    setName("");
    setDescription("");
    setImages([]);
    setAdVideo(null);
    setBusy(false);
    setStatus(null);
    setError(null);
    setCreated(null);
    setCompilePct(null);
    if (imagesRef.current) imagesRef.current.value = "";
    if (adVideoRef.current) adVideoRef.current.value = "";
  }

  return (
    <Shell>
      <div className="grid gap-6 lg:grid-cols-[420px_1fr]">
        <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 shadow-[0_0_50px_rgba(0,0,0,0.35)]">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-xs font-medium text-lime-300/90">Studio</div>
              <div className="mt-1 text-lg font-semibold tracking-tight">Register</div>
            </div>
          </div>

          <div className="mt-5 space-y-4">
            <div className="rounded-xl border border-white/10 bg-black/25 p-4">
              <div className="text-xs font-medium text-zinc-400">Checklist</div>
              <div className="mt-3 grid gap-2 text-xs">
                <div className={name.trim() ? "text-lime-200" : "text-zinc-500"}>
                  {name.trim() ? "✓" : "•"} Product name
                </div>
                <div className={images.length >= 2 ? "text-lime-200" : "text-zinc-500"}>
                  {images.length >= 2 ? "✓" : "•"} Photos (min 2) — {images.length} selected
                </div>
                <div className={adVideo ? "text-lime-200" : "text-zinc-500"}>
                  {adVideo ? "✓" : "•"} Ad video <span className="text-zinc-600">(optional)</span>
                </div>
                <div className={mindARLoaded ? "text-lime-200" : "text-zinc-600"}>
                  {mindARLoaded ? "✓" : "○"} MindAR compile <span className="text-zinc-600">(optional)</span>
                </div>
              </div>
            </div>

            <div>
              <label className="block text-xs text-zinc-400">Product name</label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                disabled={busy}
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm outline-none ring-lime-400/30 focus:ring-2"
                placeholder="e.g. Vietnamese Coffee"
              />
            </div>

            <div>
              <label className="block text-xs text-zinc-400">Description</label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                disabled={busy}
                rows={4}
                className="mt-1 w-full resize-none rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm outline-none ring-lime-400/30 focus:ring-2"
                placeholder="Optional notes (used for internal labeling)."
              />
            </div>

            <div>
              <label className="block text-xs text-zinc-400">
                Product photos <span className="text-zinc-600">(min 2, recommended 5–10)</span>
              </label>
              <input
                ref={imagesRef}
                type="file"
                accept="image/*"
                multiple
                disabled={busy}
                onChange={(e) => setImages(Array.from(e.target.files || []))}
                className="mt-1 w-full text-sm text-zinc-300 file:mr-3 file:rounded-lg file:border-0 file:bg-lime-400 file:px-3 file:py-2 file:text-sm file:font-semibold file:text-black hover:file:bg-lime-300"
              />
              <div className="mt-1 text-xs text-zinc-500">{images.length} selected</div>
            </div>

            <div>
              <label className="block text-xs text-zinc-400">
                Ad video <span className="text-zinc-600">(from PixVerse web; WebM with alpha recommended)</span>
              </label>
              <input
                ref={adVideoRef}
                type="file"
                accept="video/*"
                disabled={busy}
                onChange={(e) => setAdVideo(e.target.files?.[0] || null)}
                className="mt-1 w-full text-sm text-zinc-300 file:mr-3 file:rounded-lg file:border-0 file:bg-white/10 file:px-3 file:py-2 file:text-sm file:font-semibold file:text-white hover:file:bg-white/15"
              />
              <div className="mt-1 text-xs text-zinc-500">{adVideo ? adVideo.name : "Required"}</div>
            </div>

            <div className="space-y-2">
              {compilePct !== null && (
                <div className="text-xs text-lime-200">
                  Tracking compile: {Math.max(0, Math.min(100, Math.round(compilePct * 100)))}%
                </div>
              )}
              {status && <div className="text-xs text-lime-200">{status}</div>}
              {error && <div className="text-xs text-red-300">{error}</div>}
            </div>

            <div className="flex gap-2">
              <button
                onClick={register}
                disabled={!canSubmit}
                className="flex-1 rounded-lg bg-lime-400 px-4 py-2 text-sm font-semibold text-black shadow-[0_0_30px_rgba(34,197,94,0.25)] transition hover:bg-lime-300 disabled:opacity-40"
              >
                {busy ? "Working..." : "Register product"}
              </button>
              <button
                onClick={reset}
                disabled={busy}
                className="rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-sm font-semibold text-white transition hover:bg-white/10 disabled:opacity-40"
              >
                Reset
              </button>
            </div>
          </div>
        </section>

        <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 shadow-[0_0_50px_rgba(0,0,0,0.35)]">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-xs font-medium text-zinc-400">Preview</div>
              <div className="mt-1 text-lg font-semibold tracking-tight">Advertising Output</div>
            </div>
            {created?.id && (
              <a
                href={`/products/${created.id}`}
                className="rounded-lg border border-lime-400/25 bg-lime-400/10 px-3 py-1.5 text-xs font-semibold text-lime-200 transition hover:bg-lime-400/15"
              >
                Open details
              </a>
            )}
          </div>

          {!created ? (
            <div className="mt-10 flex flex-col items-center justify-center gap-3 text-center text-zinc-500">
              <div className="flex h-16 w-16 items-center justify-center rounded-2xl border border-white/10 bg-black/30">
                <div className="h-6 w-6 rounded-full bg-lime-400/30 shadow-[0_0_22px_rgba(34,197,94,0.25)]" />
              </div>
              <div className="text-sm">Your uploaded ad video and tracking artifacts will appear here</div>
            </div>
          ) : (
            <div className="mt-5 grid gap-4">
              {created.ad_video_url ? (
                <video
                  src={created.ad_video_url}
                  controls
                  playsInline
                  className="w-full rounded-xl border border-white/10 bg-black/40"
                />
              ) : (
                <div className="rounded-xl border border-white/10 bg-black/30 p-4 text-sm text-zinc-400">
                  No video returned yet.
                </div>
              )}

              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-xl border border-white/10 bg-black/25 p-4">
                  <div className="text-xs font-medium text-zinc-400">Tracking target</div>
                  <div className="mt-2 text-sm text-white">{created.mind_target_url ? "Ready" : "Missing"}</div>
                  {created.mind_target_url && (
                    <a
                      href={created.mind_target_url}
                      target="_blank"
                      className="mt-2 inline-flex text-xs font-semibold text-lime-300 hover:text-lime-200"
                    >
                      Download .mind
                    </a>
                  )}
                </div>

                <div className="rounded-xl border border-white/10 bg-black/25 p-4">
                  <div className="text-xs font-medium text-zinc-400">QR</div>
                  <div className="mt-2 text-sm text-white">{created.qr_url ? "Ready" : "Missing"}</div>
                  {created.qr_url && (
                    <a
                      href={created.qr_url}
                      target="_blank"
                      className="mt-2 inline-flex text-xs font-semibold text-lime-300 hover:text-lime-200"
                    >
                      Open QR image
                    </a>
                  )}
                </div>
              </div>

              <div className="rounded-xl border border-white/10 bg-black/25 p-4">
                <div className="text-xs font-medium text-zinc-400">Product ID</div>
                <div className="mt-2 break-all font-mono text-xs text-zinc-200">{created.id}</div>
              </div>
            </div>
          )}
        </section>
      </div>
    </Shell>
  );
}
