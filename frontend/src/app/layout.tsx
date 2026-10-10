import "./globals.css";
import type { Metadata } from "next";
export const metadata: Metadata = { title: "Call Intelligence", description: "Local-first call summaries and analytics" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
