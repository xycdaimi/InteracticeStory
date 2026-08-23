import type { Metadata } from "next";
import { Instrument_Sans } from "next/font/google";
import "./globals.css";

const sans = Instrument_Sans({
  variable: "--font-sans",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "裂变剧场",
  description: "灵感入局，故事图裂变",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className={`${sans.variable} font-sans antialiased`}>
        {children}
      </body>
    </html>
  );
}
