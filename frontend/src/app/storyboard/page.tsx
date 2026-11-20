'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, Clapperboard, Trash2 } from 'lucide-react';
import { api, ApiError, Compilation } from '@/lib/api';

export default function StoryboardListPage() {
  const [items, setItems] = useState<Compilation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    api.listCompilations()
      .then(setItems)
      .catch((err) => setError(err instanceof ApiError ? err.message : '加载失败'))
      .finally(() => setLoading(false));
  }, []);

  const handleDelete = async (comp: Compilation) => {
    if (!window.confirm('删掉这段短片故事板？')) return;
    try {
      await api.deleteCompilation(comp.id);
      setItems((prev) => prev.filter((c) => c.id !== comp.id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除失败');
    }
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 space-y-6">
      <Link href="/" className="text-primary min-h-[44px] inline-flex items-center gap-1.5 text-sm font-medium">
        <ArrowLeft aria-hidden className="h-4 w-4" />回到故事记录
      </Link>

      <h1 className="text-2xl font-bold text-ink flex items-center gap-2">
        <Clapperboard aria-hidden className="h-6 w-6 text-primary" />短片故事板
      </h1>
      <p className="text-sm text-muted">这里只有文字稿和画面提示词，系统不生成真实影像。</p>

      {error && <p className="rounded-btn bg-danger-soft text-danger p-4">{error}</p>}
      {loading ? (
        <p className="text-muted">正在读……</p>
      ) : items.length === 0 ? (
        <p className="text-muted">还没有短片。回到故事记录，选一段「用这段做短片」。</p>
      ) : (
        <ul className="space-y-3">
          {items.map((c) => (
            <li key={c.id} className="rounded-card border border-hairline bg-card p-4 flex items-center justify-between gap-3 flex-wrap">
              <Link href={`/storyboard/${c.id}`} className="text-lg font-bold text-primary">
                {c.title || '一段回忆短片'}
                <span className="ml-2 text-sm font-normal text-muted">
                  {c.prompt_package?.scenes.length ?? 0} 段 · 约 {c.prompt_package?.total_seconds ?? 0} 秒
                </span>
              </Link>
              <button onClick={() => handleDelete(c)}
                className="min-h-[44px] px-4 rounded-btn bg-card border border-hairline text-danger inline-flex items-center gap-1.5">
                <Trash2 aria-hidden className="h-4 w-4" />删掉
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
