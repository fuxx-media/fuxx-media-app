import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MediaOS Phase 0.1",
  description: "Technical foundation status for MediaOS.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="de">
      <body>{children}</body>
    </html>
  );
}
