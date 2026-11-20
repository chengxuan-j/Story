import type { Config } from 'tailwindcss';

/** 语义设计令牌：主题只改 CSS 变量，组件一律用语义类。 */
const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: 'var(--canvas)',
        card: { DEFAULT: 'var(--card)', soft: 'var(--card-soft)' },
        ink: 'var(--ink)',
        muted: 'var(--muted)',
        faint: 'var(--faint)',
        primary: {
          DEFAULT: 'var(--primary)',
          strong: 'var(--primary-strong)',
          soft: 'var(--primary-soft)',
          softer: 'var(--primary-softer)',
        },
        'on-primary': 'var(--on-primary)',
        danger: { DEFAULT: 'var(--danger)', soft: 'var(--danger-soft)' },
        success: { DEFAULT: 'var(--success)', soft: 'var(--success-soft)' },
        warning: { DEFAULT: 'var(--warning)', soft: 'var(--warning-soft)' },
        hairline: { DEFAULT: 'var(--hairline)', strong: 'var(--hairline-strong)' },
        butter: 'var(--butter)',
        lilac: { DEFAULT: 'var(--lilac)', soft: 'var(--lilac-soft)' },
        coral: 'var(--coral)',
        accent: { DEFAULT: 'var(--accent)', soft: 'var(--accent-soft)' },
      },
      borderRadius: {
        card: 'var(--radius-card)',
        btn: 'var(--radius-btn)',
        input: 'var(--radius-input)',
        pill: '9999px',
      },
      boxShadow: {
        card: 'var(--shadow-card)',
        btn: 'var(--shadow-btn)',
        float: 'var(--shadow-float)',
      },
    },
  },
  plugins: [],
};

export default config;
