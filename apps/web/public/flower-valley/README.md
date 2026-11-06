# Original Gladeye Flower Valley

本目录是参考 Flower Valley / Fernhollow 效果的本地运行包，采集日期 2026-11-06。
原版场景已通过本地浏览器实际运行验证。MotionSites 的预览地址为
<https://motionsites.ai/?prompt=fernhollow>，场景脚本与资源来自 <https://www.gladeye.com/>。

## 文件

- `runtime.js`：原始 webpack runtime，逐字节保留。
- `vendor.js`：通过 TypeScript AST 提取的 200 个原始模块工厂及其静态依赖，注册为 chunk 90002。
  包括原版 Three.js r154、Valley 类、地形算法、着色器和后处理。不运行原站 Next.js 页面启动代码。
- `fallback.jpg`：本地运行原版场景时截取的静帧，用于加载与 WebGL 失败回退。
- `index.html` / `scene.js`：本项目编写的最小容器与生命周期、输入消息适配器。
- `valley/`：原始相机 GLB、RGBA 图集、地形、尘埃、暗角和光束纹理，保持原文件名与内容。
- `dependency-report.json`：原始文件 URL、源文件和模块工厂 SHA-256、依赖图及补丁文本。
- `SHA256SUMS`：本地原版脚本及场景素材的校验值。

## 唯一原脚本补丁

在模块 889 的现有 Valley 类定义结束处将其导出到 iframe 自己的 window，供本地适配器启动。
除此之外保留原模块工厂内容，包括其原始版权和许可注释。

```js
// 原文
}},en=n(1944)
// 本地包
}};window.__GE={Valley:et,audioStore:Y};var en=n(1944)
```

不修改原版几何、随机数、花叶数量、相机、材质、光照或后处理参数。
此来源记录不作素材许可授权的声明。

## 原始脚本来源

以下路径以 `https://www.gladeye.com/_next/static/chunks/` 为根：

- `webpack-a76c04a7ba9aa4ef.js`
- `app/page-4c279de0997d388f.js`
- `450-96e2a31dde902aa5.js`
- `123-3b7f3df3cc5866d7.js`
- `785-3ec288b614fa287f.js`
- `b536a0f1-51636bd4ac051d8f.js`
- `596-40a806be0d0d2bb3.js`
- `780-35f43a00462f78e8.js`
- `131-8efcfd03f067c029.js`
- `567-6466d5cc81546a43.js`

原素材以 `https://www.gladeye.com/valley/` 为根：

- `camera-path07.glb`
- `flowers/pool_summer.png`、`flowers/pool_winter.png`
- `terrain.png`、`vignette.png`、`dust-particle.png`
- `rays/ray1.png`、`rays/ray2.png`、`rays/ray3.png`

## 宿主适配

本地 `scene.js` 显式启动原版类，保留开场转镜和持续镜头路径。
背景暂停需要同时停止主 RAF 和原虚拟滚动器，不能只调用其中一个。
减少动态偏好只跳过开场转镜并固定场景，不替换渲染实现。
使用 `yingxu:original-flower-valley` 消息协议转发指针、滚轮、尺寸与可见性。
父子双方均校验消息 origin 和 source。原版 CTA 的全局散开交互不绑定到业务按钮。

没有挂载原站 React 页面、站点导航、统计或音频初始化。所有实际加载均为本地脚本和纹理。
iframe 使用本地 CSP，仅允许自身脚本、资源、必要的纹理 data/blob URL 和 GUI 内联样式。
同源 iframe 用于隔离场景的 DOM、CSS 与全局变量。

原版桌面场景包含约 96 万个点；窄屏或矮屏沿用原版性能模式（约 18 万个点和简化后处理）。
正常画面保留原版 Bloom、边缘景深、RGB 分离和轻微颗粒；不加入额外屏幕噪点。
