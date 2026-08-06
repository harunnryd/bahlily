import type { ReactNode } from "react";
import { Providers } from "@/lib/providers";
import "./globals.css";

export const metadata = {
  title: "Bahlily",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="bg-zinc-950 text-zinc-100 min-h-screen">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
