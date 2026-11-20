'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { ArrowLeft, Clapperboard, Trash2 } from 'lucide-react';
import { api, ApiError, Compilation } from '@/lib/api';
import { PromptCopyButton, StoryboardPlayer, StoryboardSceneList } from '@/components/StoryboardPlayer';

export default function CompilationPage() {
  const params = useParams<{ id: string }>();
  const [comp, setComp] = useState<Compilation | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const id = Number(params?.id);
    if (!Number.isFinite(id)) { setError('这段短片不存在'); setLoading(false); return; }
    api.getCompilation(id)
      .then(setComp)
      .catch((err) => setError(err instanceof ApiError ? err.message : '加载失败'))
      .finally(() => setLoading(false));
  }, [params]);

  const handleDelete = async () => {
    if (!comp) return;
    if (!window.confirm('删掉这段短片故事板？')) return;
    try {
      await api.deleteCompilation(comp.id);
      window.location.href = '/storyboard';
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除失败');
    }
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-6 space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <Link href="/storyboard" className="text-primary min-h-[44px] inline-flex items-center gap-1.5 text-sm font-medium">
          <ArrowLeft aria-hidden className="h-4 w-4" />回到短片列表
        </Link>
        {comp && (
          <div className="flex items-center gap-2">
            <PromptCopyButton compilation={comp} />
            <button onClick={handleDelete}
              className="min-h-[44px] px-4 rounded-btn bg-card border border-hairline text-danger hover:bg-danger-soft inline-flex items-center gap-1.5">
              <Trash2 aria-hidden className="h-4 w-4" />删掉这段
            </button>
          </div>
        )}
      </div>

      {comp && (
        <div>
          <h1 className="text-2xl font-bold text-ink flex items-center gap-2">
            <Clapperboard aria-hidden className="h-6 w-6 text-primary" />{comp.title || '一段回忆短片'}
          </h1>
          <p className="mt-1 text-sm text-muted">这里只有文字稿和画面提示词，本系统不替您生成画面。</p>
        </div>
      )}

      {error && <p className="rounded-btn bg-danger-soft text-danger p-4">{error}</p>}
      {loading ? (
        <p className="text-muted text-lg">正在整理……</p>
      ) : comp ? (
        <>
          <StoryboardPlayer compilation={comp} />
          <hr className="border-hairline" />
          <StoryboardSceneList compilation={comp} />
          <p className="text-sm text-muted leading-relaxed">
            想变成真正的短片，可以把上面的提示词复制到您常用的视频工具里自己做。
          </p>
        </>
      ) : null}
    </div>
  );
}
