/** 前端 API 封装：走 Next rewrites 到后端 :8100。 */

export interface Turn {
  role: 'user' | 'assistant';
  content: string;
  scene?: string;
}

export interface Story {
  id: number;
  title: string;
  summary: string;
  raw_dialogue: Turn[];
  input_type: string;
  created_at: string;
}

export interface StoryboardScene {
  index: number;
  story_id: number;
  era: string;
  title: string;
  display_time: string;
  place: string;
  emotion_tone: string;
  duration_seconds: number;
  narration: string;
  narration_source: string;
  visual_prompt: string;
  source_evidence: string;
}

export interface ScriptScene {
  scene_no: number;
  story_id: number;
  time: string;
  place: string;
  characters: string;
  action: string;
  dialogue: string;
  narration: string;
}

export interface Shot {
  shot_no: number;
  /** 归属场次：一场可以拆多镜，所以镜头数 ≠ 场次数 */
  scene_no: number;
  story_id: number;
  duration_seconds: number;
  shot_size: string;
  visual: string;
  /** 这一镜给观众什么信息（导演表的第三列） */
  audience: string;
  /** 怎么切进来/切出去（导演表的第四列） */
  transition: string;
  action: string;
  dialogue: string;
  ambience: string;
}

export interface VideoPrompt {
  shot_no: number;
  prompt: string;
}

export interface ArtDesign {
  characters: { name: string; age: string; hair: string; costume: string; traits: string }[];
  scenes: { name: string; description: string }[];
  props: { name: string; description: string }[];
}

export interface QaNotes {
  uncertain: string[];
  adapted: string[];
}

export interface PromptPackage {
  title: string;
  perspective: string;
  total_seconds: number;
  requested_seconds: number;
  disclaimer: string;
  scenes: StoryboardScene[];
  render_engine: null;
  llm_used: boolean;
  synopsis: string;
  script: ScriptScene[];
  shot_list: Shot[];
  art_design: ArtDesign;
  video_prompts: VideoPrompt[];
  qa_notes: QaNotes;
}

export interface Compilation {
  id: number;
  title: string;
  perspective: string;
  status: string;
  story_ids: number[];
  prompt_package: PromptPackage | null;
  created_at: string;
  video_url: null;
  rendered: boolean;
}

export class ApiError extends Error {
  constructor(message: string, public status?: number) {
    super(message);
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: init?.body instanceof FormData
      ? init?.headers
      : { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  });
  if (!res.ok) {
    let msg = `请求失败 (${res.status})`;
    try {
      const data = await res.json();
      msg = data.detail || msg;
    } catch { /* ignore */ }
    throw new ApiError(msg, res.status);
  }
  return res.json();
}

export const api = {
  health: () => req<{ status: string; api_configured: boolean }>('/health'),

  nextTurn: (turns: Turn[]) =>
    req<{ question: string; focus: string; done: boolean; offer: boolean; source: string }>(
      '/story/next', { method: 'POST', body: JSON.stringify({ turns }) }
    ),

  listStories: () => req<Story[]>('/stories'),

  createStory: (body: { content: string; input_type?: string; turns?: Turn[] }) =>
    req<Story>('/stories', { method: 'POST', body: JSON.stringify(body) }),

  deleteStory: (id: number) =>
    req<{ deleted: boolean }>(`/stories/${id}`, { method: 'DELETE' }),

  createCompilation: (body?: { story_ids?: number[]; total_seconds?: number }) =>
    req<Compilation>('/compilations', {
      method: 'POST', body: JSON.stringify(body || {}),
    }),

  listCompilations: () => req<Compilation[]>('/compilations'),

  getCompilation: (id: number) => req<Compilation>(`/compilations/${id}`),

  deleteCompilation: (id: number) =>
    req<{ deleted: boolean }>(`/compilations/${id}`, { method: 'DELETE' }),

  transcribe: async (blob: Blob, filename = 'audio.webm') => {
    const fd = new FormData();
    fd.append('file', blob, filename);
    return req<{ text: string }>('/speech/transcribe', { method: 'POST', body: fd });
  },

  tts: (text: string) =>
    req<{ audio_url: string }>('/speech/tts', {
      method: 'POST', body: JSON.stringify({ text }),
    }),
};
