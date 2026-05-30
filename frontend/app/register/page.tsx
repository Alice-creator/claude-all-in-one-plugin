"use client";

import { useState, useRef, useEffect } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type RegisteredProduct = {
  id: string;
  name: string;
  ad_video_url: string | null;
  mind_target_url: string | null;
  created_at: string;
};

let _Compiler: any = null;
async function getMindARCompiler() {
  if (_Compiler) return _Compiler;
  const mod = await import(/* webpackIgnore: true */ "https://cdn.jsdelivr.net/npm/mind-ar@1.2.5/dist/mindar-image.prod.js" as any);
  _Compiler = mod.Compiler;
  return _Compiler;
}

async function compileMindTarget(imageFiles: File[]): Promise<Blob> {
  const Compiler = await getMindARCompiler();
  const compiler = new Compiler();

  const images = await Promise.all(
    imageFiles.map(
      (f) =>
        new Promise<HTMLImageElement>((resolve) => {
          const img = new Image();
          img.onload = () => resolve(img);
          img.src = URL.createObjectURL(f);
        })
    )
  );

  await compiler.compileImageTargets(images, (_p: number) => {});
  const buffer = await compiler.exportData();
  return new Blob([buffer], { type: "application/octet-stream" });
}

export default function RegisterPage() {
  const [name, setName] = useState("");
  const [images, setImages] = useState<File[]>([]);
  const [adVideo, setAdVideo] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [compileProgress, setCompileProgress] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [products, setProducts] = useState<RegisteredProduct[]>([]);
  const [mindARLoaded, setMindARLoaded] = useState(false);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const videoInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetchProducts();
    getMindARCompiler().then(() => setMindARLoaded(true)).catch(() => {});
  }, []);

  async function fetchProducts() {
    try {
      const res = await fetch(`${API}/recognition/registered`);
      setProducts(await res.json());
    } catch {}
  }

  async function deleteProduct(id: string, name: string) {
    if (!confirm(`Delete "${name}"?`)) return;
    await fetch(`${API}/recognition/registered/${id}`, { method: "DELETE" });
    fetchProducts();
  }

  async function register() {
    if (!name.trim() || images.length === 0 || busy || !mindARLoaded) return;
    setBusy(true);
    setStatus(null);

    try {
      setCompileProgress("Compiling AR target… (this takes ~30s)");
      const mindBlob = await compileMindTarget(images);
      setCompileProgress(null);

      setStatus("Uploading and computing embeddings…");
      const fd = new FormData();
      fd.append("name", name.trim());
      images.forEach((img) => fd.append("images", img));
      if (adVideo) fd.append("ad_video", adVideo);
      fd.append("mind_target", new File([mindBlob], "target.mind"));

      const res = await fetch(`${API}/recognition/register`, { method: "POST", body: fd });
      if (!res.ok) throw new Error((await res.json()).detail || "Failed");
      const data = await res.json();
      setStatus(`Registered "${data.name}" ✓`);
      setName("");
      setImages([]);
      setAdVideo(null);
      if (imageInputRef.current) imageInputRef.current.value = "";
      if (videoInputRef.current) videoInputRef.current.value = "";
      fetchProducts();
    } catch (e: any) {
      setStatus(`Error: ${e.message}`);
    } finally {
      setBusy(false);
      setCompileProgress(null);
    }
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white flex flex-col items-center py-12 px-4">
      <div className="w-full max-w-xl">

        <h1 className="text-2xl font-bold mb-1">AuraAd — Product Registry</h1>
        <p className="text-sm text-gray-500 mb-8">Register a product with reference photos so the AR camera can recognize and track it.</p>

        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 space-y-5">

          <div>
            <label className="text-xs text-gray-400 mb-1 block">Product name</label>
            <input
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-gray-500"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Highlands Coffee Can"
            />
          </div>

          <div>
            <label className="text-xs text-gray-400 mb-1 block">
              Product photos <span className="text-gray-600">(5–10 images, different angles — used for recognition + AR tracking)</span>
            </label>
            <input
              ref={imageInputRef}
              type="file"
              accept="image/*"
              multiple
              onChange={(e) => setImages(Array.from(e.target.files || []))}
              className="w-full text-sm text-gray-400 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:bg-gray-700 file:text-white file:text-sm cursor-pointer"
            />
            {images.length > 0 && (
              <p className="text-xs text-gray-500 mt-1">{images.length} image{images.length > 1 ? "s" : ""} selected</p>
            )}
          </div>

          <div>
            <label className="text-xs text-gray-400 mb-1 block">
              Video ad <span className="text-gray-600">(WebM with alpha — plays anchored to product in AR)</span>
            </label>
            <input
              ref={videoInputRef}
              type="file"
              accept="video/*"
              onChange={(e) => setAdVideo(e.target.files?.[0] || null)}
              className="w-full text-sm text-gray-400 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:bg-gray-700 file:text-white file:text-sm cursor-pointer"
            />
            {adVideo && <p className="text-xs text-gray-500 mt-1">{adVideo.name}</p>}
          </div>

          <button
            onClick={register}
            disabled={busy || !name.trim() || images.length === 0 || !mindARLoaded}
            className="w-full py-2.5 bg-white text-black rounded-xl font-semibold text-sm disabled:opacity-30 hover:bg-gray-200"
          >
            {busy ? "Registering…" : !mindARLoaded ? "Loading AR library…" : "Register Product"}
          </button>

          {compileProgress && (
            <div className="text-sm text-yellow-400 flex items-center gap-2">
              <span className="animate-pulse">⬤</span> {compileProgress}
            </div>
          )}
          {status && !compileProgress && (
            <p className={`text-sm ${status.startsWith("Error") ? "text-red-400" : "text-green-400"}`}>
              {status}
            </p>
          )}
        </div>

        {/* Products list */}
        <div className="mt-8">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-400">
              Registered products <span className="text-gray-600">({products.length})</span>
            </h2>
            <button onClick={fetchProducts} className="text-xs text-gray-600 hover:text-gray-400">↻ Refresh</button>
          </div>

          {products.length === 0 ? (
            <div className="bg-gray-900 border border-gray-800 rounded-xl px-4 py-6 text-center text-gray-600 text-sm">
              No products registered yet
            </div>
          ) : (
            <div className="space-y-2">
              {products.map((p) => (
                <div key={p.id} className="bg-gray-900 border border-gray-800 rounded-xl px-4 py-3 flex items-center justify-between">
                  <div>
                    <p className="font-medium text-sm">{p.name}</p>
                    <p className="text-xs text-gray-600 mt-0.5">{new Date(p.created_at).toLocaleString()}</p>
                  </div>
                  <div className="flex gap-2 items-center">
                    {p.mind_target_url
                      ? <span className="text-xs bg-blue-900 text-blue-400 px-2 py-0.5 rounded-full">AR ready</span>
                      : <span className="text-xs bg-gray-800 text-gray-500 px-2 py-0.5 rounded-full">no AR target</span>
                    }
                    {p.ad_video_url
                      ? <span className="text-xs bg-green-900 text-green-400 px-2 py-0.5 rounded-full">has video</span>
                      : <span className="text-xs bg-gray-800 text-gray-500 px-2 py-0.5 rounded-full">no video</span>
                    }
                    <button
                      onClick={() => deleteProduct(p.id, p.name)}
                      className="text-xs text-red-500 hover:text-red-400 px-1"
                    >✕</button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <p className="text-center text-xs text-gray-700 mt-8">
          AR camera: <a href={`${API}/static/scan.html`} className="underline" target="_blank">{API}/static/scan.html</a>
        </p>
      </div>
    </div>
  );
}
