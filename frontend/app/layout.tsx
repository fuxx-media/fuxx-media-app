import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MediaOS Phase 3",
  description: "Interne Vorgangs- und providerunabhängige Simulationsgrundlage.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="de">
      <body>{children}</body>
    </html>
  );
}
