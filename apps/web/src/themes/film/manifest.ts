/** 绯红剧场插件声明；新增主题目录可被注册表自动发现。 */
import { lazy } from 'react';
import type { ThemeManifest } from '../types';
import './theme.css';
const manifest: ThemeManifest = {
  ...{
    id: 'film',
    name: '绯红剧场',
    english: 'ROUGE CINEMA',
    tag: '婚纱 · 电影叙事',
    image: '/images/theme-cinema.webp',
    secondary: '/images/theme-rose.webp',
    description: '以你为名，演一幕属于你们的心动。',
    layout: 'cinema',
    headline: ['以你为名', '一幕心动'],
    subtitle: '让每个平凡瞬间，都有电影的回响。',
    signature: 'Made of moments.',
    mood: '电影叙事',
    tokens: {
      '--bg': '#f9f4f4',
      '--surface': '#fffbfb',
      '--surface-up': '#efdee6',
      '--text': '#57444f',
      '--muted': '#8b727e',
      '--accent': '#9d6c8c',
      '--accent-text': '#9d6c8c',
      '--accent-bright': '#e4a7b7',
      '--accent-ink': '#ffffff',
      '--button-bg': '#805371',
      '--accent-rgb': '157, 108, 140',
      '--scene-rgb': '170, 124, 155',
      '--scene-secondary': '#dec6da',
      '--border': '#57444f26',
      '--control-border': '#8b727e',
      '--success': '#a8d1b2',
      '--shadow': '0 18px 56px #00000035',
      '--display-font': "'Songti SC', 'Noto Serif SC', 'SimSun', Georgia, serif",
    },
    version: '1.1.0',
    order: 1,
  },
  atelier: {
    canvasPosition: '76% 30%',
    coverPosition: '76% center',
    headline: ['把心动的模样，', '拍成一场梦。'],
    palette: ['#dec6da', '#efdee6', '#f9f4f4'],
  },
  Hero: lazy(() => import('./Hero')),
  Intro: lazy(() => import('./Intro')),
};
export default manifest;
