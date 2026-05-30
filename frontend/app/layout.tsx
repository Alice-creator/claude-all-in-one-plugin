import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AuraAd",
  description: "Point your camera. The ad plays itself. AR product recognition powered by CLIP.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-[#050607] text-zinc-100">
        <div className="pointer-events-none fixed inset-0 [background:radial-gradient(1200px_circle_at_10%_10%,rgba(34,197,94,0.18),transparent_55%),radial-gradient(900px_circle_at_90%_20%,rgba(16,185,129,0.12),transparent_52%),radial-gradient(900px_circle_at_50%_100%,rgba(34,197,94,0.10),transparent_55%)]" />
        <div className="relative">{children}</div>
      </body>
    </html>
  );
}
