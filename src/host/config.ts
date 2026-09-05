import path from 'node:path'
import * as fs from 'node:fs'

export interface HostConfig {
  /** 主 API / 静态资源 / 桥接层 共用端口 */
  port: number
  /** TTS 代理服务端口 */
  ttsPort: number
  /** 监听地址 */
  host: string
  /** 仓库根目录（编译产物相对推导） */
  rootDir: string
  /** 视频与故事输出目录（apifile） */
  outputDir: string
  /** 内置资源目录（models/images/voices） */
  resourceDir: string
  /** webrenderer 构建产物目录 */
  webRendererDir: string
  /** 内置默认配置目录（user-configs） */
  defaultConfigDir: string
  /** 运行时可写配置目录（save-config 目标，load 优先级更高） */
  runtimeConfigDir: string
  /** 无头浏览器渲染工作进程数量 */
  workers: number
  /** 每个渲染工作进程完成多少次导出后回收重建（0 = 不回收） */
  workerRecycleExports: number
  /** ffmpeg 视频编码器：auto | nvenc | amd | intel | cpu | libx264 */
  ffmpegEncoder: string
  /** 日志级别 */
  logLevel: string
  /** Playwright channel 偏好顺序 */
  browserChannels: string[]
  /** 显式指定浏览器可执行文件（优先于 channel） */
  browserExecutablePath: string | null
  /** 附加 Chrome 启动参数（空格分隔） */
  extraChromeArgs: string[]
  /** Linux 无头 GPU 是否启用 --use-angle=gl */
  linuxGpuAngle: boolean
}

function intEnv(name: string, defaultValue: number): number {
  const raw = process.env[name]
  if (!raw) return defaultValue
  const parsed = parseInt(raw, 10)
  return Number.isFinite(parsed) ? parsed : defaultValue
}

function boolEnv(name: string, defaultValue: boolean): boolean {
  const raw = process.env[name]
  if (raw === undefined || raw === '') return defaultValue
  return !['0', 'false', 'no', 'off'].includes(raw.toLowerCase())
}

/**
 * 计算仓库根目录：优先从编译产物位置推导（out-host/host → 根目录），
 * 推导失败时回退到 process.cwd()。
 */
function resolveRootDir(): string {
  const derived = path.resolve(__dirname, '..', '..')
  if (fs.existsSync(path.join(derived, 'resources', 'builtin'))) {
    return derived
  }
  return path.resolve(process.cwd())
}

export function loadHostConfig(): HostConfig {
  const rootDir = resolveRootDir()
  const isLinux = process.platform === 'linux'

  return {
    port: intEnv('MSS_PORT', 9881),
    ttsPort: intEnv('MSS_TTS_PORT', 9882),
    host: process.env.MSS_HOST || '0.0.0.0',
    rootDir,
    outputDir: path.resolve(rootDir, process.env.MSS_OUTPUT_DIR || 'apifile'),
    resourceDir: path.resolve(rootDir, process.env.MSS_RESOURCE_DIR || 'resources/builtin'),
    webRendererDir: path.resolve(rootDir, process.env.MSS_WEB_RENDERER_DIR || 'out/webrenderer'),
    defaultConfigDir: path.resolve(rootDir, 'user-configs'),
    runtimeConfigDir: path.resolve(rootDir, process.env.MSS_CONFIG_DIR || 'user-configs-runtime'),
    workers: Math.max(1, intEnv('MSS_WORKERS', 1)),
    workerRecycleExports: Math.max(0, intEnv('MSS_WORKER_RECYCLE_EXPORTS', 5)),
    ffmpegEncoder: (process.env.MSS_FFMPEG_ENCODER || 'auto').toLowerCase(),
    logLevel: process.env.MSS_LOG_LEVEL || 'info',
    browserChannels: (process.env.MSS_BROWSER_CHANNELS || 'msedge,chrome,chromium')
      .split(',')
      .map((c) => c.trim())
      .filter(Boolean),
    browserExecutablePath: process.env.MSS_BROWSER_EXECUTABLE || null,
    extraChromeArgs: (process.env.MSS_CHROME_ARGS || '')
      .split(' ')
      .map((a) => a.trim())
      .filter(Boolean),
    linuxGpuAngle: isLinux && boolEnv('MSS_LINUX_GPU_ANGLE', true)
  }
}
