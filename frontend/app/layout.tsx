import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Noto_Sans_Arabic, Space_Grotesk } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/Providers";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });
const display = Space_Grotesk({ variable: "--font-display", subsets: ["latin"] });
const mono = JetBrains_Mono({ variable: "--font-mono", subsets: ["latin"] });
const arabic = Noto_Sans_Arabic({ variable: "--font-arabic", subsets: ["arabic"] });

export const metadata: Metadata = {
  title: { default: "NeuroQueue: brain MRI triage", template: "%s | NeuroQueue" },
  description: "NeuroQueue sorts brain MRI scans so the most pressing are read first. Decision support only, not a diagnosis. Every scan is read by a radiologist.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${inter.variable} ${display.variable} ${mono.variable} ${arabic.variable} antialiased`}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
