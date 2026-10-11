import type { Metadata, Viewport } from "next";
import { Inter, Source_Serif_4 } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const serif = Source_Serif_4({ subsets: ["latin"], variable: "--font-serif4", display: "swap" });

export const metadata: Metadata = {
  title: { default: "WEZA — Tell WEZA what financing you need", template: "%s · WEZA" },
  description:
    "WEZA connects people and businesses seeking financing with participating financial institutions — no core-banking integration required.",
};

export const viewport: Viewport = { themeColor: "#2E8BC9", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${serif.variable}`}>
      <body className="min-h-screen font-sans text-[15px] leading-relaxed">{children}</body>
    </html>
  );
}
