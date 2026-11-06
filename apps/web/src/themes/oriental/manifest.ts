/** 东方喜事插件声明；新增主题目录可被注册表自动发现。 */
import { lazy } from 'react';
import type { ThemeManifest } from '../types';
import './theme.css';
const manifest: ThemeManifest = {
  ...{
    id: 'oriental',
    name: '东方喜事',
    english: 'MODERN HERITAGE',
    tag: '婚纱 · 新中式',
    image: '/images/oriental-wedding.webp',
    secondary: '/images/oriental-wedding.webp',
    description: '一抹中国红，把郑重的喜欢写进光影。',
    layout: 'oriental',
    headline: ['一抹东方红', '一生郑重'],
    subtitle: '把含蓄的爱意，写成一场盛大的喜事。',
    signature: '良辰 · 喜事',
    mood: '浪漫柔光',
    tokens: {
      '--bg': '#fcf6f1',
      '--surface': '#fffdf8',
      '--surface-up': '#f3e4db',
      '--text': '#5d453f',
      '--muted': '#96786c',
      '--accent': '#b37867',
      '--accent-text': '#b37867',
      '--accent-bright': '#b34740',
      '--accent-ink': '#ffffff',
      '--button-bg': '#8c5c4e',
      '--accent-rgb': '179, 120, 103',
      '--scene-rgb': '198, 151, 123',
      '--scene-secondary': '#efd2bb',
      '--border': '#5d453f26',
      '--control-border': '#96786c',
      '--success': '#3c6647',
      '--shadow': '0 18px 56px #4e342b0c',
      '--display-font': "'Songti SC', 'Noto Serif SC', 'SimSun', Georgia, serif",
    },
    version: '1.1.0',
    order: 5,
  },
  atelier: {
    canvasPosition: '50% 30%',
    coverPosition: '50% 40%',
    headline: ['把心动的模样，', '拍成一场梦。'],
    palette: ['#efd2bb', '#f3e4db', '#fcf6f1'],
  },
  Hero: lazy(() => import('./Hero')),
  Intro: lazy(() => import('./Intro')),
};
export default manifest;
