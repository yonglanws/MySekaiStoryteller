import express, { Router } from 'express'
import * as fs from 'node:fs'
import type { HostConfig } from '../config'

/**
 * 静态资源托管：
 * - /                      → webrenderer 构建产物（渲染工作进程页面）
 * - /resources/builtin/*   → 内置 Live2D 模型 / 背景图 / 语音（替代 mss://builtin）
 * - /apifile/*             → API 故事 JSON 与导出视频
 * express.static 自带路径穿越防护（拒绝 .. 段）。
 */
export function createStaticRouter(config: HostConfig): Router {
  const router = Router()

  if (!fs.existsSync(config.webRendererDir)) {
    throw new Error(
      `Web renderer build not found at ${config.webRendererDir}. Run "npm run build:web" first.`
    )
  }

  router.use('/resources/builtin', express.static(config.resourceDir))
  router.use('/apifile', express.static(config.outputDir, { index: false }))
  router.use(express.static(config.webRendererDir, { index: 'index.html' }))

  return router
}
