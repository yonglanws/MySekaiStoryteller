import { defineConfig } from 'vite'
import { resolve } from 'path'

/**
 * webrenderer 构建：无头浏览器渲染工作进程页面。
 * root 指向 src/webrender，静态资源（live2d.min.js / live2dcubismcore.min.js）
 * 复用 src/renderer/public，构建产物输出到 out/webrenderer。
 */
export default defineConfig({
  root: 'src/webrender',
  publicDir: resolve(__dirname, 'src/renderer/public'),
  base: './',
  build: {
    outDir: resolve(__dirname, 'out/webrenderer'),
    emptyOutDir: true,
    assetsInlineLimit: 0,
    rollupOptions: {
      input: {
        index: resolve(__dirname, 'src/webrender/index.html')
      }
    }
  }
})
