import { ExportLogger } from './ExportLogger'

export interface FrameRateControllerConfig {
  targetFps: number
  maxFrameSkip: number
  enableFrameInterpolation: boolean
}

export interface FrameTiming {
  frameIndex: number
  expectedTime: number
  actualTime: number
  delta: number
  isSkipped: boolean
}

/**
 * 帧率控制器
 *
 * 功能：
 * 1. 确保录制以恒定帧率进行，不受渲染卡顿影响
 * 2. 检测并处理跳帧情况
 * 3. 提供帧时间插值，平滑录制
 */
export class FrameRateController {
  private readonly logger: ExportLogger
  private readonly config: Required<FrameRateControllerConfig>
  private readonly frameInterval: number

  private startTime: number = 0
  private currentFrame: number = 0
  private skippedFrames: number = 0
  private frameTimings: FrameTiming[] = []
  private isRunning: boolean = false

  constructor(config: FrameRateControllerConfig) {
    this.config = {
      targetFps: config.targetFps,
      maxFrameSkip: config.maxFrameSkip ?? 3,
      enableFrameInterpolation: config.enableFrameInterpolation ?? true
    }
    this.frameInterval = 1000 / this.config.targetFps
    this.logger = new ExportLogger('FrameRateController')
  }

  start(): void {
    this.startTime = performance.now()
    this.currentFrame = 0
    // Removed unused _lastFrameTime initialization
    this.skippedFrames = 0
    this.frameTimings = []
    this.isRunning = true

    this.logger.info('Frame rate controller started', {
      targetFps: this.config.targetFps,
      frameInterval: this.frameInterval.toFixed(2) + 'ms'
    })
  }

  stop(): void {
    this.isRunning = false
    this.logSummary()
  }

  /**
   * 等待下一帧的正确时间点
   * 返回需要等待的时间（毫秒）
   */
  async waitForNextFrame(): Promise<number> {
    if (!this.isRunning) {
      return 0
    }

    const now = performance.now()
    const expectedTime = this.startTime + this.currentFrame * this.frameInterval
    const waitTime = Math.max(0, expectedTime - now)

    if (waitTime > 0) {
      await this.sleep(waitTime)
    }

    const actualTime = performance.now()
    const delta = actualTime - expectedTime

    const timing: FrameTiming = {
      frameIndex: this.currentFrame,
      expectedTime,
      actualTime,
      delta,
      isSkipped: false
    }

    // 检测跳帧
    if (delta > this.frameInterval * this.config.maxFrameSkip) {
      const skippedCount = Math.floor(delta / this.frameInterval)
      this.skippedFrames += skippedCount
      timing.isSkipped = true

      this.logger.warn(`Frame skip detected: ${skippedCount} frames, delta=${delta.toFixed(2)}ms`)

      // 调整当前帧索引以补偿跳帧
      this.currentFrame += skippedCount
    }

    this.frameTimings.push(timing)
    this.currentFrame++

    // 限制记录数量，防止内存溢出
    if (this.frameTimings.length > 1000) {
      this.frameTimings = this.frameTimings.slice(-500)
    }

    return waitTime
  }

  /**
   * 获取当前应该渲染的帧索引
   * 用于跳过中间帧以保持同步
   */
  getCurrentFrameIndex(): number {
    if (!this.isRunning) return 0

    const elapsed = performance.now() - this.startTime
    return Math.floor(elapsed / this.frameInterval)
  }

  /**
   * 检查是否需要渲染当前帧
   * 如果渲染跟不上，返回 false 以跳过此帧
   */
  shouldRenderFrame(): boolean {
    if (!this.isRunning) return true

    const now = performance.now()
    const expectedTime = this.startTime + this.currentFrame * this.frameInterval
    const delta = now - expectedTime

    // 如果延迟超过一帧，跳过此帧
    if (delta > this.frameInterval) {
      this.currentFrame++
      this.skippedFrames++
      return false
    }

    return true
  }

  /**
   * 获取当前帧率统计
   */
  getStats(): {
    targetFps: number
    actualFps: number
    averageFrameTime: number
    skippedFrames: number
    totalFrames: number
    dropRate: number
  } {
    const totalFrames = this.currentFrame
    const elapsed = performance.now() - this.startTime
    const actualFps = elapsed > 0 ? (totalFrames / elapsed) * 1000 : 0

    const avgFrameTime =
      this.frameTimings.length > 0
        ? this.frameTimings.reduce((sum, t) => sum + (t.actualTime - t.expectedTime), 0) /
          this.frameTimings.length
        : 0

    return {
      targetFps: this.config.targetFps,
      actualFps,
      averageFrameTime: avgFrameTime,
      skippedFrames: this.skippedFrames,
      totalFrames,
      dropRate: totalFrames > 0 ? this.skippedFrames / totalFrames : 0
    }
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
  }

  private logSummary(): void {
    const stats = this.getStats()
    this.logger.info('Frame rate controller summary', {
      targetFps: stats.targetFps,
      actualFps: stats.actualFps.toFixed(2),
      totalFrames: stats.totalFrames,
      skippedFrames: stats.skippedFrames,
      dropRate: (stats.dropRate * 100).toFixed(2) + '%'
    })
  }

  reset(): void {
    this.isRunning = false
    this.currentFrame = 0
    this.skippedFrames = 0
    this.frameTimings = []
  }
}
