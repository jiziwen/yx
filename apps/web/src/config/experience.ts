/** 用户端显示配置；摄影师身份与后端聊天开关、模型路由和生成风格独立。 */
export const experience = {
  defaultThemeId: 'portrait',
  photographer: {
    name: 'Lumi',
    title: '你的专属 AI 摄影师',
    opening:
      '你好呀，我是 Lumi。这里不用摆好姿势，也不急着做决定。和我说说你想留下的画面，我们一起把它整理成提案。',
  },
  guide: { maxInputLength: 500, maxMessageLength: 1200 },
};
