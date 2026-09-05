export interface ExportProgress {
  stage: 'initializing' | 'loading' | 'capturing' | 'encoding' | 'saving' | 'complete' | 'error'
  current: number
  total: number
  message: string
  percentage: number
  eta?: number
  fps?: number
}

export type ProgressCallback = (progress: ExportProgress) => void

export class ProgressTracker {
  private startTime: number = 0
  private lastUpdateTime: number = 0
  private lastFrameCount: number = 0
  private currentFps: number = 0
  private callback: ProgressCallback | null = null
  private throttleInterval: number = 100

  constructor(callback?: ProgressCallback) {
    this.callback = callback || null
  }

  start(): void {
    this.startTime = performance.now()
    this.lastUpdateTime = this.startTime
    this.lastFrameCount = 0
  }

  update(stage: ExportProgress['stage'], current: number, total: number, message: string): void {
    const now = performance.now()

    if (
      now - this.lastUpdateTime < this.throttleInterval &&
      stage !== 'complete' &&
      stage !== 'error'
    ) {
      return
    }

    this.lastUpdateTime = now

    const percentage = total > 0 ? Math.round((current / total) * 100) : 0

    let eta: number | undefined
    if (current > 0 && current < total) {
      const elapsed = now - this.startTime
      const rate = current / elapsed
      const remaining = total - current
      eta = Math.round(remaining / rate)
    }

    const elapsed = now - this.lastUpdateTime
    if (elapsed > 0 && current > this.lastFrameCount) {
      this.currentFps = Math.round(((current - this.lastFrameCount) / elapsed) * 1000)
      this.lastFrameCount = current
    }

    const progress: ExportProgress = {
      stage,
      current,
      total,
      message,
      percentage,
      eta,
      fps: this.currentFps
    }

    this.callback?.(progress)
  }

  updateUI(
    progressFill: HTMLDivElement,
    statusText: HTMLElement,
    _stage: ExportProgress['stage'],
    current: number,
    total: number,
    message: string
  ): void {
    const percentage = total > 0 ? Math.round((current / total) * 100) : 0
    progressFill.style.width = `${percentage}%`
    statusText.textContent = message
  }

  getElapsedSeconds(): number {
    return (performance.now() - this.startTime) / 1000
  }

  getCurrentFps(): number {
    return this.currentFps
  }

  setCallback(callback: ProgressCallback): void {
    this.callback = callback
  }

  complete(): void {
    this.update('complete', 1, 1, '导出完成')
  }

  error(message: string): void {
    this.update('error', 0, 1, message)
  }
}
