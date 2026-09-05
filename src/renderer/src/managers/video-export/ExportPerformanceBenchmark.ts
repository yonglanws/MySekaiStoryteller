import { ExportLogger } from './ExportLogger'

interface PerformanceWithMemory {
  memory?: {
    usedJSHeapSize: number
    totalJSHeapSize: number
    jsHeapSizeLimit: number
  }
}

export interface BenchmarkMetrics {
  testId: string
  timestamp: number
  duration: number
  fps: number
  width: number
  height: number
  totalFrames: number
  averageFrameTime: number
  minFrameTime: number
  maxFrameTime: number
  p95FrameTime: number
  p99FrameTime: number
  memoryUsage: MemoryInfo
  deviceTier: 'low' | 'mid' | 'high'
  hardwareAcceleration: boolean
  success: boolean
  error?: string
}

export interface MemoryInfo {
  usedJSHeapSize: number
  totalJSHeapSize: number
  jsHeapSizeLimit: number
}

export interface BenchmarkConfig {
  targetFPS: number
  width: number
  height: number
  snippetCount: number
  ttsEnabled: boolean
  bgmEnabled: boolean
}

export class ExportPerformanceBenchmark {
  private readonly logger: ExportLogger = new ExportLogger('ExportBenchmark')
  private benchmarks: Map<string, BenchmarkMetrics> = new Map()
  private baselineMetrics: BenchmarkMetrics | null = null

  recordBenchmark(metrics: BenchmarkMetrics): void {
    this.benchmarks.set(metrics.testId, metrics)

    if (!this.baselineMetrics) {
      this.baselineMetrics = metrics
      this.logger.info('Baseline benchmark recorded', {
        testId: metrics.testId,
        duration: metrics.duration,
        fps: metrics.fps,
        frameTime: metrics.averageFrameTime
      })
    }
  }

  getBaseline(): BenchmarkMetrics | null {
    return this.baselineMetrics
  }

  getLatestBenchmark(): BenchmarkMetrics | null {
    const benchmarks = Array.from(this.benchmarks.values())
    if (benchmarks.length === 0) return null
    return benchmarks[benchmarks.length - 1]
  }

  compareWithBaseline(current: BenchmarkMetrics): {
    improvement: number
    message: string
  } {
    if (!this.baselineMetrics) {
      return {
        improvement: 0,
        message: '无基准数据，无法比较'
      }
    }

    const baselineDuration = this.baselineMetrics.duration
    const improvement = ((baselineDuration - current.duration) / baselineDuration) * 100

    let message = ''
    if (improvement > 0) {
      message = `性能提升 ${improvement.toFixed(1)}%，导出时间从 ${baselineDuration.toFixed(1)}s 减少到 ${current.duration.toFixed(1)}s`
    } else {
      message = `性能下降 ${Math.abs(improvement).toFixed(1)}%，导出时间从 ${baselineDuration.toFixed(1)}s 增加到 ${current.duration.toFixed(1)}s`
    }

    return { improvement, message }
  }

  static detectDeviceTier(): 'low' | 'mid' | 'high' {
    const perf = performance as unknown as PerformanceWithMemory
    const memory = perf.memory
    if (!memory) return 'mid'

    const heapLimit = memory.jsHeapSizeLimit
    if (heapLimit > 2 * 1024 * 1024 * 1024) {
      return 'high'
    } else if (heapLimit > 1 * 1024 * 1024 * 1024) {
      return 'mid'
    } else {
      return 'low'
    }
  }

  static getMemoryInfo(): MemoryInfo {
    const perf = performance as unknown as PerformanceWithMemory
    const memory = perf.memory
    if (!memory) {
      return {
        usedJSHeapSize: 0,
        totalJSHeapSize: 0,
        jsHeapSizeLimit: 0
      }
    }

    return {
      usedJSHeapSize: memory.usedJSHeapSize,
      totalJSHeapSize: memory.totalJSHeapSize,
      jsHeapSizeLimit: memory.jsHeapSizeLimit
    }
  }

  async runBenchmark(config: BenchmarkConfig): Promise<BenchmarkMetrics> {
    this.logger.info('Starting performance benchmark', config)

    const startTime = performance.now()
    const frameTimes: number[] = []
    let totalFrames = 0
    const testId = `benchmark_${Date.now()}`

    try {
      for (let i = 0; i < config.snippetCount; i++) {
        const frameStart = performance.now()

        await new Promise((resolve) => setTimeout(resolve, 1000 / config.targetFPS))

        const frameEnd = performance.now()
        const frameTime = frameEnd - frameStart
        frameTimes.push(frameTime)
        totalFrames++
      }

      const duration = (performance.now() - startTime) / 1000
      const sortedTimes = [...frameTimes].sort((a, b) => a - b)
      const p95Index = Math.min(Math.floor(frameTimes.length * 0.95), frameTimes.length - 1)
      const p99Index = Math.min(Math.floor(frameTimes.length * 0.99), frameTimes.length - 1)

      const metrics: BenchmarkMetrics = {
        testId,
        timestamp: Date.now(),
        duration,
        fps: config.targetFPS,
        width: config.width,
        height: config.height,
        totalFrames,
        averageFrameTime:
          frameTimes.length > 0 ? frameTimes.reduce((a, b) => a + b, 0) / frameTimes.length : 0,
        minFrameTime: sortedTimes.length > 0 ? sortedTimes[0] : 0,
        maxFrameTime: sortedTimes.length > 0 ? sortedTimes[sortedTimes.length - 1] : 0,
        p95FrameTime: sortedTimes.length > 0 ? sortedTimes[p95Index] : 0,
        p99FrameTime: sortedTimes.length > 0 ? sortedTimes[p99Index] : 0,
        memoryUsage: ExportPerformanceBenchmark.getMemoryInfo(),
        deviceTier: ExportPerformanceBenchmark.detectDeviceTier(),
        hardwareAcceleration: false,
        success: true
      }

      this.recordBenchmark(metrics)
      this.logger.info('Benchmark completed', {
        testId,
        duration,
        averageFrameTime: metrics.averageFrameTime.toFixed(2)
      })

      return metrics
    } catch (error) {
      const duration = (performance.now() - startTime) / 1000
      const metrics: BenchmarkMetrics = {
        testId,
        timestamp: Date.now(),
        duration,
        fps: config.targetFPS,
        width: config.width,
        height: config.height,
        totalFrames,
        averageFrameTime: 0,
        minFrameTime: 0,
        maxFrameTime: 0,
        p95FrameTime: 0,
        p99FrameTime: 0,
        memoryUsage: ExportPerformanceBenchmark.getMemoryInfo(),
        deviceTier: ExportPerformanceBenchmark.detectDeviceTier(),
        hardwareAcceleration: false,
        success: false,
        error: error instanceof Error ? error.message : String(error)
      }

      this.recordBenchmark(metrics)
      this.logger.error('Benchmark failed', { testId, error })

      throw error
    }
  }

  getAllBenchmarks(): BenchmarkMetrics[] {
    return Array.from(this.benchmarks.values())
  }

  clearBenchmarks(): void {
    this.benchmarks.clear()
    this.baselineMetrics = null
    this.logger.info('All benchmarks cleared')
  }
}
