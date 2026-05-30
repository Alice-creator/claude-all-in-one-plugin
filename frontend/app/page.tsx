"use client";

import Link from "next/link";
import Shell from "./components/Shell";

export default function BrandPortal() {
  return (
    <Shell>
      <section className="relative overflow-hidden rounded-2xl border border-lime-400/15 bg-white/[0.03] p-8 shadow-[0_0_60px_rgba(34,197,94,0.08)]">
        <div className="absolute inset-0 [background:radial-gradient(800px_circle_at_0%_0%,rgba(34,197,94,0.12),transparent_55%),radial-gradient(700px_circle_at_100%_0%,rgba(34,197,94,0.08),transparent_60%)]" />
        <div className="relative">
          <div className="inline-flex items-center gap-2 rounded-full border border-lime-400/20 bg-lime-400/10 px-3 py-1 text-[11px] font-medium text-lime-200">
            <span className="h-1.5 w-1.5 rounded-full bg-lime-400 shadow-[0_0_16px_rgba(34,197,94,0.55)]" />
            AR product recognition
          </div>

          <h1 className="mt-4 text-balance text-3xl font-semibold leading-tight tracking-tight md:text-4xl">
            Point your camera.<br />
            <span className="text-lime-400">The ad plays itself.</span>
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-zinc-300">
            Register a product with a few photos. AuraAd recognizes it in real time and overlays your ad video
            directly on the product — tracked as the camera moves. No app needed on the customer&apos;s phone.
          </p>

          <div className="mt-6 flex flex-col gap-3 sm:flex-row">
            <Link
              href="/studio"
              className="inline-flex items-center justify-center rounded-lg bg-lime-400 px-4 py-2 text-sm font-semibold text-black shadow-[0_0_26px_rgba(34,197,94,0.28)] transition hover:bg-lime-300"
            >
              Open Studio
            </Link>
            <Link
              href="/products"
              className="inline-flex items-center justify-center rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-sm font-semibold text-white transition hover:bg-white/10"
            >
              View Products
            </Link>
          </div>
        </div>
      </section>

      <section className="mt-8 grid gap-4 md:grid-cols-3">
        {[
          {
            title: "Instant recognition",
            body: "CLIP identifies your product from any angle or partial view — even in difficult lighting.",
          },
          {
            title: "AR video overlay",
            body: "Your ad video plays on top of the product and follows it as the camera moves.",
          },
          {
            title: "No app to install",
            body: "Customers scan via a browser link. Works on any smartphone with a camera.",
          },
        ].map((x) => (
          <div
            key={x.title}
            className="rounded-xl border border-white/10 bg-white/[0.03] p-5 shadow-[0_0_40px_rgba(0,0,0,0.35)]"
          >
            <div className="text-sm font-semibold text-white">{x.title}</div>
            <div className="mt-2 text-sm text-zinc-400">{x.body}</div>
          </div>
        ))}
      </section>
    </Shell>
  );
}
