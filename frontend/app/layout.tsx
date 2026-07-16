import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MediaOS Phase 0",
  description: "Infrastructure and workflow-kernel status for MediaOS.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="de">
      <body>{children}</body>
    </html>
  );
}
