/** 海岛叙事插件声明；新增主题目录可被注册表自动发现。 */
import { lazy } from 'react';
import type { ThemeManifest } from '../types';
import './theme.css';
const manifest: ThemeManifest = {
  ...{
    id: 'coast',
    name: '海岛叙事',
    english: 'COASTAL VOWS',
    tag: '婚纱 · 自然光',
    image: '/images/hero-coast.webp',
    secondary: '/images/theme-rose.webp',
    description: '让海风翻动裙摆，让日落成为见证。',
    layout: 'coast',
    headline: ['海风有信', '爱有回响'],
    subtitle: '把日落、海风和你，一起写进我们的故事。',
    signature: 'Somewhere, with you.',
    mood: '自然纪实',
    tokens: {
      '--bg': '#f6f9f8',
      '--surface': '#fcfffe',
      '--surface-up': '#e4efee',
      '--text': '#3f555b',
      '--muted': '#6d8489',
      '--accent': '#5c8b94',
      '--accent-text': '#5c8b94',
      '--accent-bright': '#6d939a',
      '--accent-ink': '#ffffff',
      '--button-bg': '#466a73',
      '--accent-rgb': '92, 139, 148',
      '--scene-rgb': '128, 170, 178',
      '--scene-secondary': '#d3e8e5',
      '--border': '#3f555b26',
      '--control-border': '#6d8489',
      '--success': '#3c6647',
      '--shadow': '0 18px 56px #4e342b0c',
      '--display-font': "'Songti SC', 'Noto Serif SC', 'SimSun', Georgia, serif",
    },
    version: '1.1.0',
    order: 4,
  },
  atelier: {
    canvasPosition: '70% 45%',
    coverPosition: '70% center',
    headline: ['把心动的模样，', '拍成一场梦。'],
    palette: ['#d3e8e5', '#e4efee', '#f6f9f8'],
  },
  Hero: lazy(() => import('./Hero')),
  Intro: lazy(() => import('./Intro')),
};
export default manifest;
