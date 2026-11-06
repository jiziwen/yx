/** 主题插件契约；视觉状态与后端 style_id、方案及上传数据隔离。 */
import type { ComponentType, LazyExoticComponent } from 'react';
export interface ThemeManifest {
  id: string;
  name: string;
  english: string;
  tag: string;
  image: string;
  secondary: string;
  description: string;
  layout: string;
  headline: string[];
  subtitle: string;
  signature: string;
  mood: string;
  tokens: Record<string, string>;
  version: string;
  order: number;
  enabled?: boolean;
  atelier?: {
    headline?: [string, string];
    subtitle?: string;
    coverImage?: string;
    coverPosition?: string;
    canvasPosition?: string;
    secondaryImage?: string;
    palette?: [string, string, string];
  };
  Hero: LazyExoticComponent<ComponentType<ThemeHeroProps>>;
  Intro: LazyExoticComponent<ComponentType<ThemeIntroProps>>;
}
export interface ThemeHeroProps {
  theme: ThemeManifest;
  onCreate: (theme: ThemeManifest) => void;
  busy?: boolean;
  onStart?: (brief: string) => void;
}
export interface ThemeIntroProps {
  theme: ThemeManifest;
}
