import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PDF to Anki",
  description: "Generate Anki decks and USMLE vignette questions from medical PDFs",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
