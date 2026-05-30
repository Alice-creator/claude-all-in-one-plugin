"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const nav = [
  { href: "/", label: "Home" },
  { href: "/studio", label: "Studio" },
  { href: "/products", label: "Products" },
  { href: "/scan", label: "Scan" },
];

export default function Navbar() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-50 border-b border-lime-400/15 bg-[#050607]/70 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
        <Link href="/" className="group inline-flex items-center gap-2.5">
          <img
            src="/logo.svg"
            alt="AuraAd logo"
            className="h-7 w-7 drop-shadow-[0_0_8px_rgba(74,222,128,0.55)]"
          />
          <span className="text-sm font-semibold tracking-tight">
            Aura<span className="text-lime-400">Ad</span>
          </span>
        </Link>

        <nav className="flex items-center gap-1">
          {nav.map((item) => {
            const active = pathname === item.href || pathname.startsWith(item.href + "/");
            return (
              <Link
                key={item.href}
                href={item.href}
                className={[
                  "rounded-md px-3 py-1.5 text-xs font-medium transition",
                  active
                    ? "bg-lime-400/10 text-lime-200 ring-1 ring-inset ring-lime-400/25"
                    : "text-zinc-300 hover:bg-white/5 hover:text-white",
                ].join(" ")}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}

