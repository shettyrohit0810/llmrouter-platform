import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "LLMRouter Console",
  description: "Operate LLM routers: projects, usage, experiments, registry and audit logs.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
