'use client';

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { useRouter } from 'next/navigation';
import { Clapperboard, Mic, Save, Square, Trash2, Wand2 } from 'lucide-react';
import { ApiError, api, Story, Turn } from '@/lib/api';
import { audioExtension } from '@/lib/audio';
import { DEMO_SCRIPTS, matchScriptReply } from '@/data/demo-stories';

const GREETING = '您想说说哪段往事？随便开个头，我接着问。';
const MAX_RECORD_SECONDS = 120;

function formatDate(iso: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日`;
}

/**
 * 对话式记录故事：说一句 → 追问一句 → 存下来 → 一键排成短片故事板。
 * 语音只做一次性转写，不触发任何预生成。
 */
export function StoryComposer() {
  const router = useRouter();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState('');
  const [thinking, setThinking] = useState(false);
  const [saving, setSaving] = useState(false);
  const [filmId, setFilmId] = useState<number | null>(null);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [stories, setStories] = useState<Story[]>([]);
  const [loading, setLoading] = useState(true);
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [showScripts, setShowScripts] = useState(false);
  const [demo, setDemo] = useState<{ scriptId: string; index: number; playing: boolean } | null>(null);
  const [offered, setOffered] = useState(false);
  const [starting, setStarting] = useState(false);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const usedVoiceRef = useRef(false);
  const requestSeqRef = useRef(0);
  const scriptTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startingRef = useRef(false);
  const activeStreamRef = useRef<MediaStream | null>(null);
  const mountedRef = useRef(true);

  const userTurns = turns.filter((t) => t.role === 'user');
  const userCount = userTurns.length;
  const demoScript = demo ? DEMO_SCRIPTS.find((s) => s.id === demo.scriptId) : undefined;

  const flash = (text: string) => {
    setNotice(text);
    setTimeout(() => setNotice(''), 3000);
  };

  /** 让仍在飞行中的追问/脚本定时器失效，避免旧回复塞回已清空的对话。 */
  const cancelPendingReply = () => {
    requestSeqRef.current += 1;
    if (scriptTimerRef.current) {
      clearTimeout(scriptTimerRef.current);
      scriptTimerRef.current = null;
    }
    setThinking(false);
  };

  const loadStories = useCallback(async () => {
    try {
      setStories(await api.listStories());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '故事列表没读出来');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void loadStories(); }, [loadStories]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns, thinking]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestSeqRef.current += 1;
      if (scriptTimerRef.current) clearTimeout(scriptTimerRef.current);
      if (timerRef.current) clearInterval(timerRef.current);
      activeStreamRef.current?.getTracks().forEach((t) => t.stop());
      mediaRecorderRef.current?.stream.getTracks().forEach((t) => t.stop());
    };
  }, []);

  useEffect(() => {
    if (!recording || seconds < MAX_RECORD_SECONDS) return;
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    setRecording(false);
    mediaRecorderRef.current?.stop();
  }, [recording, seconds]);

  // 演示脚本自动播放
  useEffect(() => {
    if (!demo || !demo.playing || !demoScript) return;
    if (demo.index >= demoScript.turns.length) return;
    const current = demoScript.turns[demo.index];
    const delay = demo.index === 0 ? 400 : 600 + Math.min(1500, (current?.content.length || 10) * 70);
    const timer = setTimeout(() => {
      const nextTurn = demoScript.turns[demo.index];
      setTurns((prev) => [...prev, nextTurn]);
      setDemo((d) => {
        if (!d) return d;
        const nextIndex = d.index + 1;
        return { ...d, index: nextIndex, playing: nextIndex < demoScript.turns.length };
      });
      if (demo.index + 1 >= demoScript.turns.length) flash('演示结束，可以点「存到我的故事」。');
    }, delay);
    return () => clearTimeout(timer);
  }, [demo, demoScript]);

  const startDemo = (scriptId: string) => {
    cancelPendingReply();
    usedVoiceRef.current = false;
    setTurns([]); setDraft(''); setError(''); setShowScripts(false); setOffered(false);
    setDemo({ scriptId, index: 0, playing: true });
  };
  const exitDemo = () => {
    cancelPendingReply();
    usedVoiceRef.current = false;
    setDemo(null); setTurns([]); setDraft(''); setOffered(false);
  };

  const sendText = async () => {
    const text = draft.trim();
    if (!text || thinking || saving || recording || transcribing || startingRef.current) return;
    const seq = requestSeqRef.current + 1;
    requestSeqRef.current = seq;
    const nextTurns: Turn[] = [...turns, { role: 'user', content: text }];
    setTurns(nextTurns); setDraft(''); setError('');

    // 脚本匹配只在演示模式生效，避免真实聊天被 demo 台词劫持
    const scripted = demo ? matchScriptReply(text) : null;
    if (scripted) {
      setThinking(true);
      scriptTimerRef.current = setTimeout(() => {
        scriptTimerRef.current = null;
        if (seq !== requestSeqRef.current) return;
        setTurns([...nextTurns, { role: 'assistant', content: scripted }]);
        setThinking(false);
      }, 450);
      return;
    }

    setThinking(true);
    try {
      const r = await api.nextTurn(nextTurns);
      if (seq !== requestSeqRef.current) return;
      setTurns([...nextTurns, { role: 'assistant', content: r.question }]);
      if (r.offer) setOffered(true);
    } catch (err) {
      if (seq !== requestSeqRef.current) return;
      setTurns([...nextTurns, {
        role: 'assistant',
        content: '我这会儿没太听清，您接着说，说完了直接点下面保存也行。',
      }]);
      setError(err instanceof ApiError ? err.message : '追问暂时没接上，不影响保存。');
    } finally {
      if (seq === requestSeqRef.current) setThinking(false);
    }
  };

  const handleSave = async () => {
    if (saving || recording || transcribing || starting || startingRef.current) return;
    const content = userTurns.map((t) => t.content.trim()).filter(Boolean).join('\n');
    if (content.length < 2) { setError('再多说一句吧，我还没听明白这段事。'); return; }
    // 保存后对话会被清空；先让飞行中的追问失效，避免它把旧内容塞回来
    cancelPendingReply();
    setSaving(true); setError('');
    try {
      const story = await api.createStory({
        content,
        input_type: usedVoiceRef.current ? 'voice' : 'text',
        turns,
      });
      setStories((prev) => [story, ...prev]);
      setTurns([]); setDemo(null); usedVoiceRef.current = false; setOffered(false);
      flash('这段存好了，可以做成短片。');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '没存上，等会儿再试试。');
    } finally {
      setSaving(false);
    }
  };

  const startRecording = async () => {
    if (startingRef.current) return;
    setError('');
    if (typeof window !== 'undefined' &&
        (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia)) {
      setError('当前地址下浏览器不给用麦克风：可以先用文字写，或者在电脑上用 localhost 打开再录音。');
      return;
    }
    startingRef.current = true;
    setStarting(true);
    let stream: MediaStream | null = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!mountedRef.current) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      activeStreamRef.current = stream;
      const mr = new MediaRecorder(stream);
      chunksRef.current = [];
      mr.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      mr.onstop = async () => {
        stream?.getTracks().forEach((t) => t.stop());
        if (activeStreamRef.current === stream) activeStreamRef.current = null;
        if (!mountedRef.current) return;
        // 浏览器实际产出的格式可能是 webm/ogg/mp4，按真实 MIME 决定后缀
        const recorderType = mr.mimeType || chunksRef.current[0]?.type || 'audio/webm';
        const blob = new Blob(chunksRef.current, { type: recorderType });
        if (blob.size === 0) { setError('这次没录到声音，再试一次吧。'); return; }
        setTranscribing(true);
        try {
          const res = await api.transcribe(blob, `story.${audioExtension(blob.type)}`);
          if (!mountedRef.current) return;
          const text = (res.text || '').trim();
          if (!text) { setError('没听清，您用文字补一句也行。'); return; }
          usedVoiceRef.current = true;
          setDraft((prev) => (prev.trim() ? `${prev.trim()} ${text}` : text));
          flash('听好了，没错就点「发送」。');
        } catch (err) {
          if (!mountedRef.current) return;
          setError(err instanceof ApiError ? err.message : '语音没转成文字，您先用文字说一句。');
        } finally {
          if (mountedRef.current) setTranscribing(false);
        }
      };
      mediaRecorderRef.current = mr;
      mr.start(1000); setSeconds(0); setRecording(true);
      timerRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
    } catch {
      stream?.getTracks().forEach((t) => t.stop());
      if (activeStreamRef.current === stream) activeStreamRef.current = null;
      setError('没能打开麦克风，您可以先用文字说。');
    } finally {
      startingRef.current = false;
      if (mountedRef.current) setStarting(false);
    }
  };

  const stopRecording = () => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    setRecording(false);
    mediaRecorderRef.current?.stop();
  };

  const handleDelete = async (story: Story) => {
    setDeletingId(story.id); setError('');
    try {
      await api.deleteStory(story.id);
      setStories((prev) => prev.filter((s) => s.id !== story.id));
      setConfirmId(null);
      flash('这段故事和它的短片稿一起删掉了。');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '没删掉，等会儿再试试。');
    } finally {
      setDeletingId(null);
    }
  };

  const handleUseForFilm = async (story: Story) => {
    setFilmId(story.id); setError('');
    try {
      const comp = await api.createCompilation({ story_ids: [story.id] });
      router.push(`/storyboard/${comp.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '短片稿没排出来，等会儿再试试。');
    } finally {
      setFilmId(null);
    }
  };

  return (
    <div className="mx-auto max-w-3xl px-4 py-8 space-y-6">
      <header className="text-center">
        <h1 className="text-3xl font-bold text-primary">🎬 故事短片工作台</h1>
        <p className="mt-2 text-muted">聊聊往事，小忆帮您排成一段短片故事板</p>
      </header>

      <section className="rounded-card border border-hairline bg-card p-5 shadow-card">
        <div className="flex items-baseline justify-between flex-wrap gap-2">
          <h2 className="flex items-center gap-2 text-lg font-bold text-ink">
            <Mic aria-hidden className="h-5 w-5 text-primary" />聊聊想做成短片的故事
          </h2>
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted">您说一句，小忆接一句</span>
            {!demo && userCount === 0 && (
              <button type="button" onClick={() => setShowScripts((v) => !v)}
                className="min-h-[40px] px-3 rounded-btn bg-card border border-hairline text-sm text-muted hover:border-primary">
                <Clapperboard aria-hidden className="h-4 w-4 inline" /> {showScripts ? '收起脚本' : '演示脚本'}
              </button>
            )}
          </div>
        </div>

        {showScripts && !demo && (
          <div className="mt-3 rounded-card border border-hairline bg-card-soft p-3">
            <p className="text-sm text-muted">选一段，自动一句句铺开；铺完可以直接保存成故事。</p>
            <div className="mt-2 flex flex-wrap gap-3">
              {DEMO_SCRIPTS.map((s) => (
                <button key={s.id} type="button" onClick={() => startDemo(s.id)}
                  className="min-h-[56px] flex-1 min-w-[240px] text-left rounded-btn border border-hairline bg-card px-4 py-3 hover:border-primary">
                  <span className="block text-lg font-bold text-ink">{s.title}
                    {s.id === 'gloves' && (
                      <span className="ml-2 rounded-pill bg-primary px-2 py-0.5 text-xs text-on-primary align-middle">推荐</span>
                    )}
                  </span>
                  <span className="block text-sm text-muted">{s.subtitle}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {demo && demoScript && (
          <div className="mt-3 rounded-btn bg-warning-soft p-3 flex flex-wrap items-center gap-3">
            <span className="text-sm text-warning font-bold">
              演示中：{demoScript.title}（{Math.min(demo.index, demoScript.turns.length)}/{demoScript.turns.length}）
            </span>
            <button type="button" onClick={() => setDemo((d) => (d ? { ...d, playing: !d.playing } : d))}
              className="min-h-[44px] px-4 rounded-btn bg-card border border-hairline text-warning font-bold">
              {demo.playing ? '暂停' : '继续'}
            </button>
            <button type="button" onClick={() => { setTurns([]); setOffered(false); setDemo({ scriptId: demo.scriptId, index: 0, playing: true }); }}
              className="min-h-[44px] px-4 rounded-btn bg-card border border-hairline text-warning font-bold">重来</button>
            <button type="button" onClick={exitDemo}
              className="min-h-[44px] px-4 rounded-btn bg-card border border-hairline text-muted font-bold">退出演示</button>
          </div>
        )}

        <div ref={scrollRef} className="mt-3 max-h-[420px] overflow-y-auto rounded-card bg-primary-softer p-3 space-y-3">
          <Bubble role="assistant">{GREETING}</Bubble>
          {turns.map((t, i) => (
            <div key={i}>
              {t.scene && (
                <div className="my-3 flex items-center gap-2 text-sm text-muted">
                  <span className="h-px flex-1 bg-hairline" />
                  <span className="shrink-0 rounded-pill bg-primary-soft px-3 py-1 text-primary font-bold">{t.scene}</span>
                  <span className="h-px flex-1 bg-hairline" />
                </div>
              )}
              <Bubble role={t.role}>{t.content}</Bubble>
            </div>
          ))}
          {thinking && <Bubble role="assistant"><span className="text-muted">小忆在想…</span></Bubble>}
        </div>

        {!demo && (
          <div className="mt-3">
            <textarea value={draft} onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault(); void sendText();
                }
              }}
              rows={2} placeholder="想到哪儿说到哪儿，比如：我十七岁那年去修水库……"
              className="w-full rounded-input border border-hairline bg-card p-3 text-lg leading-relaxed text-ink placeholder:text-faint focus:border-primary focus:outline-none" />
            <div className="mt-2 flex flex-wrap items-center gap-3">
              {recording ? (
                <button type="button" onClick={stopRecording}
                  className="min-h-[56px] px-6 rounded-btn bg-danger text-on-primary text-lg font-bold inline-flex items-center gap-1.5">
                  <Square aria-hidden className="h-5 w-5" />说完了（{seconds} 秒）
                </button>
              ) : (
                <button type="button" onClick={startRecording} disabled={transcribing || thinking || saving || starting}
                  className="min-h-[56px] px-6 rounded-btn bg-card border border-hairline-strong text-primary text-lg font-bold disabled:opacity-50 inline-flex items-center gap-1.5">
                  <Mic aria-hidden className="h-5 w-5" />{starting ? '正在打开…' : '用嘴说'}
                </button>
              )}
              <button type="button" onClick={() => void sendText()} disabled={!draft.trim() || thinking || recording || transcribing}
                className="min-h-[56px] px-6 rounded-btn bg-primary hover:bg-primary-strong text-on-primary shadow-btn text-lg font-bold disabled:opacity-50">
                发送
              </button>
              {transcribing && <span className="text-muted text-lg">正在听您说……</span>}
              {userCount > 0 && (
                <button type="button" onClick={() => { cancelPendingReply(); setTurns([]); setDraft(''); setOffered(false); usedVoiceRef.current = false; }}
                  className="ml-auto min-h-[48px] px-4 rounded-btn bg-card border border-hairline text-muted">重新说一段</button>
              )}
            </div>
          </div>
        )}

        {demo && <p className="mt-3 text-sm text-warning">演示模式：台词按脚本自动往下走，铺完或点「暂停」后可以直接保存。</p>}

        {offered && userCount > 0 && (
          <div className="mt-3 rounded-btn bg-accent-soft border border-primary text-ink p-3 flex flex-wrap items-center justify-between gap-2">
            <span className="text-sm">小忆说这段可以做成短剧了。想做就先存下来，再到下面点「用这段做短片」。</span>
            <button type="button" onClick={handleSave} disabled={saving || recording || transcribing || starting}
              className="min-h-[44px] px-4 rounded-btn bg-primary text-on-primary font-bold disabled:opacity-50">
              好，先存下来
            </button>
          </div>
        )}

        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-muted">
            {userCount === 0 ? '说一句就能开始，小忆会顺着您的话往下问。' : `已经说了 ${userCount} 句，可以接着说，也可以随时全部存下来。`}
          </p>
          <button type="button" onClick={handleSave} disabled={saving || recording || transcribing || starting || userCount === 0}
            className="min-h-[56px] px-6 rounded-btn bg-primary hover:bg-primary-strong text-on-primary shadow-btn text-lg font-bold disabled:opacity-50 inline-flex items-center gap-1.5">
            <Save aria-hidden className="h-5 w-5" />{saving ? '正在存……' : '存到我的故事'}
          </button>
        </div>

        {error && <p className="mt-3 rounded-btn bg-danger-soft text-danger p-3">{error}</p>}
        {notice && <p className="mt-3 rounded-btn bg-success-soft text-success p-3">{notice}</p>}
      </section>

      <section className="rounded-card border border-hairline bg-card p-5 shadow-card">
        <div className="flex items-baseline justify-between">
          <h2 className="text-lg font-bold text-ink">我存的故事</h2>
          <span className="text-sm text-muted">{loading ? '正在读……' : `共 ${stories.length} 段`}</span>
        </div>
        {!loading && stories.length === 0 && (
          <p className="mt-2 text-muted">还没有存过。聊完一段，点「存到我的故事」就出现在这里。</p>
        )}
        <ul className="mt-2 space-y-3">
          {stories.map((story) => (
            <li key={story.id} className="rounded-card border border-hairline bg-card-soft p-4">
              <div className="flex items-baseline justify-between gap-2 flex-wrap">
                <p className="text-lg font-bold text-ink">{story.title || '一段回忆'}</p>
                <span className="text-sm text-muted">{formatDate(story.created_at)}</span>
              </div>
              <p className="mt-1 text-ink leading-relaxed whitespace-pre-wrap max-h-40 overflow-y-auto">{story.summary}</p>
              {confirmId === story.id ? (
                <div className="mt-3 flex flex-wrap items-center gap-3 rounded-btn bg-danger-soft p-3">
                  <p className="text-danger">删掉这段故事，和用它做过的短片也会一起删掉，找不回来。确定吗？</p>
                  <button type="button" onClick={() => handleDelete(story)} disabled={deletingId === story.id}
                    className="min-h-[48px] px-5 rounded-btn bg-danger text-on-primary font-bold disabled:opacity-50">
                    {deletingId === story.id ? '正在删……' : '确定删除'}
                  </button>
                  <button type="button" onClick={() => setConfirmId(null)}
                    className="min-h-[48px] px-5 rounded-btn bg-card border border-hairline text-ink font-bold">先不删</button>
                </div>
              ) : (
                <div className="mt-3 flex flex-wrap gap-3">
                  <button type="button" onClick={() => handleUseForFilm(story)} disabled={filmId === story.id}
                    className="min-h-[48px] px-5 rounded-btn bg-primary text-on-primary font-bold disabled:opacity-50 inline-flex items-center gap-1.5">
                    <Wand2 aria-hidden className="h-5 w-5" />{filmId === story.id ? '正在排……' : '用这段做短片'}
                  </button>
                  <button type="button" onClick={() => setConfirmId(story.id)}
                    className="min-h-[48px] px-5 rounded-btn bg-card border border-hairline text-ink font-bold hover:text-danger inline-flex items-center gap-1.5">
                    <Trash2 aria-hidden className="h-5 w-5" />删除
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      </section>

      <ShortcutsLink />
    </div>
  );
}

function ShortcutsLink() {
  const router = useRouter();
  return (
    <div className="text-center">
      <button onClick={() => router.push('/storyboard')}
        className="min-h-[48px] px-5 rounded-btn bg-card border border-hairline text-primary font-bold">
        查看已生成的短片故事板 →
      </button>
    </div>
  );
}

function Bubble({ role, children }: { role: 'user' | 'assistant'; children: ReactNode }) {
  const isUser = role === 'user';
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      {!isUser && (
        <span className="mr-2 mt-1 shrink-0 w-9 h-9 rounded-pill bg-primary-soft text-primary flex items-center justify-center text-sm font-bold">小忆</span>
      )}
      <p className={`max-w-[82%] rounded-card px-4 py-3 text-lg leading-relaxed whitespace-pre-wrap ${
        isUser ? 'bg-primary text-on-primary rounded-br-sm' : 'bg-card border border-hairline text-ink rounded-bl-sm'
      }`}>{children}</p>
    </div>
  );
}
