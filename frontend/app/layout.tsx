import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'VIAHIND Vision | Security Alerts & CCTV Analytics',
  description:
    'Multi-floor PG CCTV analytics platform with AI fight-classifier detection, incident review, and authorized evidence handling.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
      </head>
      <body>{children}</body>
    </html>
  );
}
