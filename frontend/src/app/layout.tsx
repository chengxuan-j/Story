import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: '故事短片工作台',
  description: '聊聊往事，排成短片故事板',
};

export const dynamic = 'force-dynamic';

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen bg-canvas text-ink">{children}</body>
    </html>
  );
}
