import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "US Market Movers",
  description: "Yahoo Finance Lite - US-only market movers",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
