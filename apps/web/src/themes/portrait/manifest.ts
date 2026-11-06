/** 雾光艺廊插件声明；新增主题目录可被注册表自动发现。 */
import { lazy } from 'react';
import type { ThemeManifest } from '../types';
import './theme.css';
const manifest: ThemeManifest = {
  ...{
    id: 'portrait',
    name: '雾光艺廊',
    english: 'MIST & MUSE',
    tag: '写真 · 柔光肖像',
    image: '/images/theme-muse.webp',
    secondary: '/images/theme-rose.webp',
    description: '把独一无二的你，留在光里。',
    layout: 'muse',
    headline: ['光落在', '你身上'],
    subtitle: '每一个真实的你，都是一束光。',
    signature: 'muse.',
    mood: '浪漫柔光',
    tokens: {
      '--bg': '#faf6fb',
      '--surface': '#fffcff',
      '--surface-up': '#eee4f3',
      '--text': '#504653',
      '--muted': '#817087',
      '--accent': '#8d6a99',
      '--accent-text': '#8d6a99',
      '--accent-bright': '#897297',
      '--accent-ink': '#ffffff',
      '--button-bg': '#795783',
      '--accent-rgb': '141, 106, 153',
      '--scene-rgb': '161, 132, 179',
      '--scene-secondary': '#e6d7f0',
      '--border': '#50465326',
      '--control-border': '#817087',
      '--success': '#3c6647',
      '--shadow': '0 18px 56px #4e342b0c',
      '--display-font': "'Songti SC', 'Noto Serif SC', 'SimSun', Georgia, serif",
    },
    version: '1.1.0',
    order: 2,
  },
  atelier: {
    canvasPosition: '50% 20%',
    coverPosition: '50% 40%',
    headline: ['把心动的模样，', '拍成一场梦。'],
    coverImage: '/images/theme-muse.webp',
    secondaryImage: '/images/hero-coast.webp',
    palette: ['#d4c6df', '#eed8ce', '#c6cbbd'],
  },
  Hero: lazy(() => import('./Hero')),
  Intro: lazy(() => import('./Intro')),
};
export default manifest;
