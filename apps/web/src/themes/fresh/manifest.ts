/** 晴日来信插件声明；新增主题目录可被注册表自动发现。 */
import { lazy } from 'react';
import type { ThemeManifest } from '../types';
import './theme.css';
const manifest: ThemeManifest = {
  ...{
    id: 'fresh',
    name: '晴日来信',
    english: 'LETTERS FROM SUMMER',
    tag: '写真 · 小清新',
    image: '/images/theme-fresh.webp',
    secondary: '/images/theme-fresh.webp',
    description: '收集一点日光，留住自在的自己。',
    layout: 'fresh',
    headline: ['风是自由的', '你也是'],
    subtitle: '在树影、微风与日常里，发现轻盈的自己。',
    signature: 'Dear sunshine,',
    mood: '自然纪实',
    tokens: {
      '--bg': '#f8faf3',
      '--surface': '#fffffb',
      '--surface-up': '#ebf0df',
      '--text': '#495345',
      '--muted': '#7d866d',
      '--accent': '#7a9160',
      '--accent-text': '#7a9160',
      '--accent-bright': '#688361',
      '--accent-ink': '#ffffff',
      '--button-bg': '#586c43',
      '--accent-rgb': '122, 145, 96',
      '--scene-rgb': '160, 181, 132',
      '--scene-secondary': '#e0eacb',
      '--border': '#49534526',
      '--control-border': '#7d866d',
      '--success': '#3c6647',
      '--shadow': '0 18px 56px #4e342b0c',
      '--display-font': "'Songti SC', 'Noto Serif SC', 'SimSun', Georgia, serif",
    },
    version: '1.1.0',
    order: 3,
  },
  atelier: {
    canvasPosition: '50% 25%',
    coverPosition: '50% 40%',
    headline: ['把心动的模样，', '拍成一场梦。'],
    palette: ['#e0eacb', '#ebf0df', '#f8faf3'],
  },
  Hero: lazy(() => import('./Hero')),
  Intro: lazy(() => import('./Intro')),
};
export default manifest;
