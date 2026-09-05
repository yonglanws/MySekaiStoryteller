import { ILogObj, Logger } from 'tslog'
import { loadHostConfig } from './config'
import { VideoApiServer } from './servers/VideoApiServer'
import { TTSServiceServer } from './servers/TTSServiceServer'
import { createBridgeRouter } from './bridge/bridgeRoutes'
import { WsHub } from './bridge/wsHub'
import { RenderPool } from './pool/renderPool'
import { createStaticRouter } from './static/staticRoutes'

/**
 * MySekaiStoryteller 纯 API 渲染宿主。
 *
 * 组成：
 * - VideoApiServer  :9881  视频导出 API（与旧版端点契约一致）
 * - 静态托管         :9881  webrenderer 页面 / 内置资源 / apifile
 * - 桥接层           :9881  /bridge/*（invoke、二进制写盘、TTS/翻译代理、WS）
 * - TTSServiceServer :9882  GPT-SoVITS 代理与角色声音管理
 * - RenderPool              无头浏览器渲染工作进程池
 */
async function bootstrap(): Promise<void> {
  const config = loadHostConfig()

  const LOG_LEVEL_IDS: Record<string, number> = {
    silly: 0,
    trace: 1,
    debug: 2,
    info: 3,
    warn: 4,
    error: 5,
    fatal: 6
  }

  const logger: Logger<ILogObj> = new Logger({
    name: 'host',
    type: 'pretty',
    minLevel: LOG_LEVEL_IDS[config.logLevel] ?? 3,
    prettyLogTemplate:
      '[{{yyyy}}-{{mm}}-{{dd}} {{hh}}:{{MM}}:{{ss}}:{{ms}}][{{logLevelName}}][{{name}}]: ',
    prettyLogTimeZone: 'local'
  })

  logger.info(
    `Starting MySekaiStoryteller host: root=${config.rootDir}, port=${config.port}, ttsPort=${config.ttsPort}, workers=${config.workers}, encoder=${config.ffmpegEncoder}`
  )

  const hub = new WsHub(logger, {
    onWorkerReady: (workerId) => pool.handleWorkerReady(workerId),
    onWorkerMessage: (workerId, message) => pool.handleWorkerMessage(workerId, message),
    onWorkerDisconnected: (workerId) => pool.handleWorkerDisconnected(workerId)
  })

  const pool = new RenderPool(logger, config, hub)

  const apiServer = new VideoApiServer(logger, {
    port: config.port,
    host: config.host,
    outputDir: config.outputDir,
    registerExtraRoutes: (app) => {
      app.use('/bridge', createBridgeRouter({ logger, config }))
      app.use(createStaticRouter(config))
      logger.info('[Host] Bridge and static routes mounted')
    }
  })

  apiServer.setDispatcher(pool)

  pool.onExportResult = (taskId, result) => {
    if (result.success) {
      apiServer.resolveExport(taskId, {
        success: true,
        videoPath: result.videoPath,
        duration: result.duration,
        frameCount: result.frameCount
      })
    } else {
      apiServer.rejectExport(taskId, new Error(result.error || 'Export failed'))
    }
  }

  apiServer.setExtraHealthProvider(() => ({
    renderPool: pool.stats(),
    host: {
      platform: process.platform,
      node: process.version,
      ffmpegEncoder: config.ffmpegEncoder
    }
  }))

  const ttsServer = new TTSServiceServer(logger, {}, config.ttsPort, config.host)

  try {
    await apiServer.start()
  } catch (error) {
    logger.error('Failed to start Video API server', error)
    process.exit(1)
  }

  // WS 升级挂在 API 服务的 HTTP server 上（同端口）
  const httpServer = apiServer.getHttpServer()
  if (!httpServer) {
    logger.error('HTTP server not available for WebSocket attachment')
    process.exit(1)
  }
  hub.attach(httpServer)

  await pool.start()

  try {
    await ttsServer.start()
  } catch (error) {
    logger.error('Failed to start TTS service server (continuing without TTS proxy)', error)
  }

  logger.info(
    `Host ready: API http://${config.host}:${config.port}/api/v1/health, TTS http://${config.host}:${config.ttsPort}/health`
  )

  let shuttingDown = false
  const shutdown = async (signal: string): Promise<void> => {
    if (shuttingDown) return
    shuttingDown = true
    logger.info(`Received ${signal}, shutting down...`)
    try {
      await pool.stop()
    } catch (err) {
      logger.warn('Pool stop failed', err)
    }
    ttsServer.stop()
    apiServer.stop()
    process.exit(0)
  }

  process.on('SIGINT', () => void shutdown('SIGINT'))
  process.on('SIGTERM', () => void shutdown('SIGTERM'))
}

void bootstrap().catch((error) => {
  console.error('Fatal: host bootstrap failed', error)
  process.exit(1)
})
