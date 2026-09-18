export const FONT_FAMILIES = [
  {
    id: 'system',
    name: '系统默认',
    description: '跟随操作系统，适合日常使用',
    cssStack: "system-ui, -apple-system, 'Segoe UI', Roboto, 'Microsoft YaHei', sans-serif",
  },
  {
    id: 'sans',
    name: '现代黑体',
    description: '清晰简洁，适合长时间编辑',
    cssStack: "'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC', sans-serif",
  },
  {
    id: 'serif',
    name: '经典宋体',
    description: '书籍质感，适合沉浸阅读',
    cssStack: "'Noto Serif CJK SC', 'Source Han Serif SC', 'Songti SC', SimSun, serif",
  },
  {
    id: 'kai',
    name: '楷体',
    description: '柔和雅致，适合文学创作',
    cssStack: "KaiTi, STKaiti, 'Kaiti SC', serif",
  },
  {
    id: 'monospace',
    name: '等宽字体',
    description: '字符等宽，便于逐字校对',
    cssStack: "'Cascadia Mono', Consolas, 'Microsoft YaHei', monospace",
  },
] as const

export type FontFamilyId = (typeof FONT_FAMILIES)[number]['id']

export const DEFAULT_FONT_FAMILY: FontFamilyId = 'system'
export const DEFAULT_FONT_SIZE = 16
export const MIN_FONT_SIZE = 12
export const MAX_FONT_SIZE = 24
