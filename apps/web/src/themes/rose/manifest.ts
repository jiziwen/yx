/** 玫瑰画廊插件声明；新增主题目录可被注册表自动发现。 */
import { lazy } from 'react';
import type { ThemeManifest } from '../types';
import './theme.css';
const manifest: ThemeManifest = {
  ...{
    id: 'rose',
    name: '玫瑰画廊',
    english: 'ROSE ATELIER',
    tag: '婚纱 · 艺术纪实',
    image: '/images/theme-rose.webp',
    secondary: '/images/theme-rose.webp',
    description: '让心动，成为值得收藏的艺术。',
    layout: 'gallery',
    headline: ['让心动', '成为艺术'],
    subtitle: '你的故事，值得被郑重收藏。',
    signature: 'Moments',
    mood: '浪漫柔光',
    tokens: {
      '--bg': '#fcf6f4',
      '--surface': '#fffdfb',
      '--surface-up': '#f2e4e6',
      '--text': '#57434c',
      '--muted': '#88707a',
      '--accent': '#a66f88',
      '--accent-text': '#a66f88',
      '--accent-bright': '#8c3c47',
      '--accent-ink': '#ffffff',
      '--button-bg': '#89556c',
      '--accent-rgb': '166, 111, 136',
      '--scene-rgb': '188, 133, 153',
      '--scene-secondary': '#edcbd7',
      '--border': '#57434c26',
      '--control-border': '#88707a',
      '--success': '#3c6647',
      '--shadow': '0 18px 56px #4e342b0c',
      '--display-font': "'Songti SC', 'Noto Serif SC', 'SimSun', Georgia, serif",
    },
    version: '1.1.0',
    order: 0,
  },
  atelier: {
    canvasPosition: '50% 35%',
    coverPosition: '50% 40%',
    headline: ['把心动的模样，', '拍成一场梦。'],
    palette: ['#edcbd7', '#f2e4e6', '#fcf6f4'],
  },
  Hero: lazy(() => import('./Hero')),
  Intro: lazy(() => import('./Intro')),
};
export default manifest;
