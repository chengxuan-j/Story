'use client';

import { useEffect, useRef, useState } from 'react';
import { Compilation, api } from '@/lib/api';

type TabKey = 'player' | 'synopsis' | 'script' | 'shots' | 'art' | 'video' | 'qa';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'player', label: '播放器' },
  { key: 'synopsis', label: '片名简介' },
  { key: 'script', label: '剧本' },
  { key: 'shots', label: '分镜表' },
  { key: 'art', label: '美术设定' },
  { key: 'video', label: '视频提示词' },
  { key: 'qa', label: '待确认' },
];

const TONE_TINTS: Record<string, string> = {
  温暖: 'bg-butter',
  自豪: 'bg-warning-soft',
  辛酸: 'bg-lilac-soft',
  平淡: 'bg-card-soft',
  创伤: 'bg-primary-soft',
  怀念: 'bg-accent-soft',
};

function Placeholder({ tone, label }: { tone: string; label: string }) {
  const tint = TONE_TINTS[tone] || TONE_TINTS['平淡'];
  return (
    <div className={`w-full aspect-video rounded-card ${tint} flex flex-col items-center justify-center text-ink text-center p-6`}>
      <span className="text-lg font-bold">{label}</span>
      <span className="text-sm opacity-80 mt-2">（画面示意占位，系统不生成影像）</span>
    </div>
  );
}

/** 逐条高亮 + TTS 念旁白；系统不生成真实画面。 */
export function StoryboardPlayer({ compilation }: { compilation: Compilation }) {
  const pkg = compilation.prompt_package;
  const scenes = pkg?.scenes ?? [];
  const [active, setActive] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [tab, setTab] = useState<TabKey>('player');
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!playing || scenes.length === 0) return;
    let cancelled = false;
    const run = async () => {
      const scene = scenes[active];
      let waited = false;
      try {
        const res = await api.tts(scene.narration);
        if (cancelled) return;
        if (res.audio_url && audioRef.current) {
          audioRef.current.src = res.audio_url;
          waited = true;
          await audioRef.current.play().catch(() => {});
        }
      } catch { /* TTS 不可用就静默走过 */ }
      if (cancelled) return;
      if (!waited) {
        await new Promise((r) => { timerRef.current = setTimeout(r, scene.duration_seconds * 1000); });
      }
    };
    run();
    return () => {
      cancelled = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      audioRef.current?.pause();
    };
  }, [playing, active, scenes]);

  const handleEnded = () => {
    if (active + 1 < scenes.length) setActive(active + 1);
    else setPlaying(false);
  };

  if (!pkg || scenes.length === 0) {
    return <div className="rounded-card border border-hairline bg-card p-6 text-muted">这段短片还没有可用的故事板。</div>;
  }

  const current = scenes[active];
  return (
    <div className="space-y-4">
      <audio ref={audioRef} onEnded={handleEnded} className="hidden" />
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h2 className="text-xl font-bold text-ink">{pkg.title}</h2>
        <span className="text-muted">共 {scenes.length} 段 · 约 {pkg.total_seconds} 秒</span>
      </div>

      <div className="flex flex-wrap gap-2 border-b border-hairline pb-2">
        {TABS.map((t) => (
          <button type="button" key={t.key} onClick={() => setTab(t.key)}
            className={`min-h-[40px] px-3 rounded-btn text-sm ${tab === t.key
              ? 'bg-primary text-on-primary font-bold'
              : 'bg-card border border-hairline text-muted'}`}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'player' && (
        <>
          <div className="flex items-center gap-3">
            <button onClick={() => setPlaying((v) => !v)}
              className="min-h-[48px] px-5 rounded-btn bg-primary hover:bg-primary-strong text-on-primary font-bold">
              {playing ? '⏸ 暂停' : '▶ 播放'}
            </button>
          </div>
          <Placeholder tone={current.emotion_tone}
            label={`第 ${current.index} 段｜${current.display_time || current.era || '时间不详'}｜${current.duration_seconds} 秒`} />
          <div className="rounded-card border border-hairline bg-card p-5">
            <div className="flex items-center gap-3 flex-wrap mb-2">
              <h3 className="text-lg font-bold text-ink">{current.title || '一段往事'}</h3>
              {current.era && <span className="text-sm bg-primary-soft text-primary rounded-btn px-2 py-0.5">{current.era}</span>}
              {current.narration_source === 'original' && (
                <span className="text-sm border border-hairline text-primary rounded-btn px-2 py-0.5">旁白是老人原话</span>
              )}
            </div>
            <p className="text-xl leading-relaxed text-ink">{current.narration}</p>
            <details className="mt-3">
              <summary className="cursor-pointer text-muted min-h-[40px] flex items-center">看这段的画面提示词</summary>
              <p className="mt-2 text-base text-muted bg-canvas rounded-btn p-3">{current.visual_prompt}</p>
              <p className="mt-2 text-sm text-muted">出处（老人原话）：{current.source_evidence}</p>
            </details>
          </div>
        </>
      )}

      {tab === 'synopsis' && (
        <section className="rounded-card border border-hairline bg-card p-5 space-y-2">
          <h3 className="text-lg font-bold text-ink">{pkg.title}</h3>
          <p className="text-base leading-relaxed text-ink">{pkg.synopsis || '（暂无简介）'}</p>
        </section>
      )}

      {tab === 'script' && (
        <section className="space-y-3">
          {pkg.script.map((s) => (
            <div key={s.scene_no} className="rounded-card border border-hairline bg-card p-4">
              <h3 className="font-bold text-ink">第 {s.scene_no} 场 · {s.time || '时间不详'} · {s.place || '地点不详'}</h3>
              {s.characters && <p className="mt-1 text-sm text-muted">出场：{s.characters}</p>}
              {s.action && <p className="mt-2 text-base text-ink">动作：{s.action}</p>}
              {s.dialogue && <p className="mt-1 text-base text-ink">对白：{s.dialogue}</p>}
              <p className="mt-1 text-base text-ink">旁白：{s.narration}</p>
            </div>
          ))}
        </section>
      )}

      {tab === 'shots' && (
        <section className="space-y-3">
          <div className="flex items-baseline justify-between flex-wrap gap-2">
            <p className="text-sm text-muted">
              共 {pkg.shot_list.length} 镜 · 合计{' '}
              {pkg.shot_list.reduce((a, s) => a + s.duration_seconds, 0)} 秒
            </p>
            <p className="text-sm text-muted">一场可拆多镜，秒数由系统分配</p>
          </div>
          <div className="overflow-x-auto rounded-card border border-hairline bg-card">
            <table className="w-full min-w-[760px] border-collapse text-left">
              <thead>
                <tr className="border-b border-hairline">
                  <th className="w-[104px] px-4 py-3 text-sm font-semibold text-muted whitespace-nowrap">镜号 / 成片时长</th>
                  <th className="w-[300px] px-4 py-3 text-sm font-semibold text-muted">画面</th>
                  <th className="px-4 py-3 text-sm font-semibold text-muted">观众看什么、知道什么</th>
                  <th className="px-4 py-3 text-sm font-semibold text-muted">怎么切</th>
                </tr>
              </thead>
              <tbody>
                {pkg.shot_list.map((s) => (
                  <tr key={s.shot_no} className="align-top border-b border-hairline last:border-0">
                    <td className="px-4 py-4 text-ink whitespace-nowrap tabular-nums">
                      {String(s.shot_no).padStart(2, '0')}
                      <span className="block text-sm text-muted">/ {s.duration_seconds} 秒</span>
                    </td>
                    <td className="px-4 py-4 text-base leading-relaxed text-ink">
                      {s.shot_size && <span className="mr-1 text-sm text-primary">{s.shot_size}</span>}
                      {s.visual}
                      {s.dialogue && <p className="mt-1 text-muted">「{s.dialogue}」</p>}
                      {s.ambience && <p className="mt-1 text-sm text-muted">环境声：{s.ambience}</p>}
                    </td>
                    <td className="px-4 py-4 text-base leading-relaxed text-ink">{s.audience || '—'}</td>
                    <td className="px-4 py-4 text-base leading-relaxed text-ink">{s.transition || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {tab === 'art' && (
        <section className="space-y-4">
          {pkg.art_design.characters.length > 0 && (
            <div className="rounded-card border border-hairline bg-card p-4">
              <h3 className="font-bold text-ink">人物</h3>
              {pkg.art_design.characters.map((c, i) => (
                <p key={i} className="mt-2 text-base text-ink">
                  {[c.name && `${c.name}`, c.age, c.hair, c.costume, c.traits].filter(Boolean).join(' · ') || '（未设定）'}
                </p>
              ))}
            </div>
          )}
          {pkg.art_design.scenes.length > 0 && (
            <div className="rounded-card border border-hairline bg-card p-4">
              <h3 className="font-bold text-ink">场景</h3>
              {pkg.art_design.scenes.map((s, i) => (
                <p key={i} className="mt-2 text-base text-ink">{s.name}：{s.description}</p>
              ))}
            </div>
          )}
          {pkg.art_design.props.length > 0 && (
            <div className="rounded-card border border-hairline bg-card p-4">
              <h3 className="font-bold text-ink">道具</h3>
              {pkg.art_design.props.map((p, i) => (
                <p key={i} className="mt-2 text-base text-ink">{p.name}：{p.description}</p>
              ))}
            </div>
          )}
          {pkg.art_design.characters.length + pkg.art_design.scenes.length + pkg.art_design.props.length === 0 && (
            <p className="text-muted">这次没有美术设定（可能是离线整理的结果）。</p>
          )}
        </section>
      )}

      {tab === 'video' && (
        <section className="space-y-3">
          <p className="text-sm text-warning">这些是文字提示词，可复制到外部视频工具使用；本系统不生成视频。</p>
          {pkg.video_prompts.map((v) => (
            <div key={v.shot_no} className="rounded-card border border-hairline bg-card p-4">
              <strong className="text-ink">镜头 {v.shot_no}</strong>
              <p className="mt-1 text-base text-muted whitespace-pre-wrap">{v.prompt}</p>
            </div>
          ))}
        </section>
      )}

      {tab === 'qa' && (
        <section className="space-y-3">
          <div className="rounded-card border border-hairline bg-card p-4">
            <h3 className="font-bold text-ink">待确认</h3>
            {pkg.qa_notes.uncertain.length
              ? <ul className="mt-2 list-disc pl-5 text-base text-ink">{pkg.qa_notes.uncertain.map((u, i) => <li key={i}>{u}</li>)}</ul>
              : <p className="mt-2 text-muted">没有需要确认的疑点。</p>}
          </div>
          <div className="rounded-card border border-hairline bg-card p-4">
            <h3 className="font-bold text-ink">改编说明</h3>
            {pkg.qa_notes.adapted.length
              ? <ul className="mt-2 list-disc pl-5 text-base text-ink">{pkg.qa_notes.adapted.map((a, i) => <li key={i}>{a}</li>)}</ul>
              : <p className="mt-2 text-muted">没有补写的台词或动作。</p>}
          </div>
        </section>
      )}

      {pkg.disclaimer && <p className="text-sm text-muted leading-relaxed">{pkg.disclaimer}</p>}
    </div>
  );
}

export function promptPackageToText(compilation: Compilation): string {
  const pkg = compilation.prompt_package;
  if (!pkg) return '';
  const out: (string | number | false)[] = [
    `# ${pkg.title}`,
    '',
    '## 一、片名与故事简介',
    pkg.synopsis || '（无）',
    '',
    '## 二、短剧剧本',
    ...pkg.script.map((s) => [
      `第 ${s.scene_no} 场｜${s.time || '时间不详'}｜${s.place || '地点不详'}`,
      s.characters && `出场：${s.characters}`,
      s.action && `动作：${s.action}`,
      s.dialogue && `对白：${s.dialogue}`,
      `旁白：${s.narration}`,
    ].filter(Boolean).join('\n')),
    '',
    '## 三、分镜表',
    '',
    '| 镜号 / 成片时长 | 画面 | 观众看什么、知道什么 | 怎么切 |',
    '| --- | --- | --- | --- |',
    ...pkg.shot_list.map((s) => {
      const visual = [
        s.shot_size ? `${s.shot_size}。` : '',
        s.visual,
        s.dialogue ? `（${s.dialogue}）` : '',
        s.ambience ? `环境声：${s.ambience}` : '',
      ].join('');
      return `| ${String(s.shot_no).padStart(2, '0')} / ${s.duration_seconds} 秒 | ${visual} | ${s.audience || '—'} | ${s.transition || '—'} |`;
    }),
    '',
    `合计 ${pkg.shot_list.reduce((a, s) => a + s.duration_seconds, 0)} 秒，与全片 ${pkg.total_seconds} 秒一致。`,
    '',
    '## 四、人物与场景美术设定',
    ...pkg.art_design.characters.map((c) => `人物：${[c.name, c.age, c.hair, c.costume, c.traits].filter(Boolean).join(' · ')}`),
    ...pkg.art_design.scenes.map((s) => `场景：${s.name}：${s.description}`),
    ...pkg.art_design.props.map((p) => `道具：${p.name}：${p.description}`),
    '',
    '## 五、逐镜头视频生成提示词',
    ...pkg.video_prompts.map((v) => `镜头 ${v.shot_no}：${v.prompt}`),
    '',
    '## 六、待确认与改编说明',
    pkg.qa_notes.uncertain.length && `待确认：\n${pkg.qa_notes.uncertain.map((u) => `- ${u}`).join('\n')}`,
    pkg.qa_notes.adapted.length && `改编：\n${pkg.qa_notes.adapted.map((a) => `- ${a}`).join('\n')}`,
    '',
    '## 附：旧版逐段故事板',
    ...pkg.scenes.map((s) => [
      `第 ${s.index} 段（${s.display_time || '时间不详'}｜${s.duration_seconds} 秒）`,
      `旁白：${s.narration}`,
      `画面：${s.visual_prompt}`,
      `出处：${s.source_evidence}`,
    ].join('\n')),
    '',
    pkg.disclaimer,
  ];
  return out.filter((x): x is string => typeof x === 'string' && x !== '').join('\n');
}

export function PromptCopyButton({ compilation }: { compilation: Compilation }) {
  const [copied, setCopied] = useState(false);
  if (!compilation.prompt_package) return null;
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(promptPackageToText(compilation));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { setCopied(false); }
  };
  return (
    <button type="button" onClick={handleCopy}
      className="min-h-[48px] px-4 rounded-btn bg-card border border-primary text-primary font-bold hover:bg-primary-soft">
      {copied ? '✅ 已复制' : '📋 复制全部提示词'}
    </button>
  );
}

export function StoryboardSceneList({ compilation }: { compilation: Compilation }) {
  const pkg = compilation.prompt_package;
  if (!pkg) return null;
  return (
    <section className="space-y-3">
      <h3 className="text-lg font-bold text-ink">故事板</h3>
      <ol className="space-y-3">
        {pkg.scenes.map((s) => (
          <li key={s.index} className="rounded-card border border-hairline bg-card p-4">
            <div className="flex items-baseline justify-between flex-wrap gap-2">
              <strong className="text-ink">{s.index}. {s.title || '一段往事'}</strong>
              <span className="text-sm text-muted">
                {s.display_time || '时间不详'} · {s.duration_seconds} 秒{s.narration_source === 'original' && ' · 原话'}
              </span>
            </div>
            <p className="mt-2 text-lg text-ink">{s.narration}</p>
            <p className="mt-2 text-base text-muted">{s.visual_prompt}</p>
          </li>
        ))}
      </ol>
      {pkg.llm_used === false && (
        <p className="text-sm text-muted">这次是离线整理的（没能连上模型），旁白直接用老人原话，画面提示为占位。</p>
      )}
    </section>
  );
}
