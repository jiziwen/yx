/** 创作方式的体验文案；可用性和全部数量限制由后端能力目录决定。 */
import { Camera, ImagePlus, Sparkles, WandSparkles } from 'lucide-react';
export type CreationMode = 'template' | 'portrait' | 'edit' | 'text';
export const creationModes = [
  {
    id: 'template',
    title: '拍一张心动同款',
    short: '拍同款',
    description: '选一张样片，让故事里的主角成为你。',
    icon: Camera,
    hint: '样片底图 + 人物参考',
    invitation:
      '选好底图和人物参考，我们保留原图站位、朝向、姿势、构图和色调，把故事里的主角换成你。',
  },
  {
    id: 'portrait',
    title: '为我设计写真',
    short: '设计写真',
    description: '带上你的照片，剩下的灵感交给我们。',
    icon: ImagePlus,
    hint: '人物参考 + 一点想象',
    invitation:
      '不必先找到一张同款。给我你的参考照，再聊聊想去的地方、喜欢的光，我陪你设计新的画面。',
  },
  {
    id: 'edit',
    title: '让照片再心动一点',
    short: '修改照片',
    description: '保留喜欢的瞬间，微调光线与小细节。',
    icon: WandSparkles,
    hint: '一张底图就可以',
    invitation: '把想改的照片放在这里吧。我们一起说清楚保留什么、改变什么，不需要另外上传人物照。',
  },
  {
    id: 'text',
    title: '从想象开始',
    short: '文字创作',
    description: '一句话，也能成为一张照片的起点。',
    icon: Sparkles,
    hint: '不需要上传照片',
    invitation:
      '这次就从一句话开始。画面里的人物由模型创作；如果想拍出你本人的模样，随时切到「设计写真」。',
  },
] as const;
