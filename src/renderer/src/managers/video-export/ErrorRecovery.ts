export enum ExportErrorCode {
  CANCELLED = 'CANCELLED',
  TIMEOUT = 'TIMEOUT',
  INVALID_CANVAS = 'INVALID_CANVAS',
  ENCODER_ERROR = 'ENCODER_ERROR',
  STORAGE_ERROR = 'STORAGE_ERROR',
  INITIALIZATION_ERROR = 'INITIALIZATION_ERROR',
  ASSET_LOADING_ERROR = 'ASSET_LOADING_ERROR',
  SNIPPET_ERROR = 'SNIPPET_ERROR',
  FFMPEG_ERROR = 'FFMPEG_ERROR',
  UNKNOWN = 'UNKNOWN'
}

export class ExportError extends Error {
  public readonly code: ExportErrorCode
  public readonly context?: Record<string, unknown>
  public readonly recoverable: boolean

  constructor(
    code: ExportErrorCode,
    message: string,
    context?: Record<string, unknown>,
    recoverable: boolean = false
  ) {
    super(message)
    this.name = 'ExportError'
    this.code = code
    this.context = context
    this.recoverable = recoverable
  }

  static cancelled(): ExportError {
    return new ExportError(ExportErrorCode.CANCELLED, '导出已被用户取消', undefined, false)
  }

  static timeout(context?: Record<string, unknown>): ExportError {
    return new ExportError(
      ExportErrorCode.TIMEOUT,
      '操作超时，请尝试减少片段数或降低分辨率',
      context,
      true
    )
  }

  static invalidCanvas(width: number, height: number): ExportError {
    return new ExportError(
      ExportErrorCode.INVALID_CANVAS,
      `画布尺寸无效: ${width}x${height}`,
      { width, height },
      false
    )
  }

  static encoderError(message: string, context?: Record<string, unknown>): ExportError {
    return new ExportError(ExportErrorCode.ENCODER_ERROR, `编码器错误: ${message}`, context, true)
  }

  static snippetError(index: number, originalError: unknown): ExportError {
    return new ExportError(
      ExportErrorCode.SNIPPET_ERROR,
      `片段 ${index} 处理失败`,
      { snippetIndex: index, error: originalError },
      true
    )
  }

  static storageError(message: string, context?: Record<string, unknown>): ExportError {
    return new ExportError(ExportErrorCode.STORAGE_ERROR, `存储错误: ${message}`, context, true)
  }

  static initializationError(message: string, context?: Record<string, unknown>): ExportError {
    return new ExportError(
      ExportErrorCode.INITIALIZATION_ERROR,
      `初始化错误: ${message}`,
      context,
      false
    )
  }

  static assetLoadingError(message: string, context?: Record<string, unknown>): ExportError {
    return new ExportError(
      ExportErrorCode.ASSET_LOADING_ERROR,
      `资源加载错误: ${message}`,
      context,
      true
    )
  }

  static ffmpegError(message: string, context?: Record<string, unknown>): ExportError {
    return new ExportError(ExportErrorCode.FFMPEG_ERROR, `FFmpeg错误: ${message}`, context, true)
  }

  static unknownError(message: string, context?: Record<string, unknown>): ExportError {
    return new ExportError(ExportErrorCode.UNKNOWN, message, context, false)
  }
}

export class ErrorRecoveryManager {
  private errorCounts: Map<ExportErrorCode, number> = new Map()
  private maxRetries: number = 3

  constructor(maxRetries: number = 3) {
    this.maxRetries = maxRetries
  }

  recordError(error: ExportError): void {
    const count = this.errorCounts.get(error.code) || 0
    this.errorCounts.set(error.code, count + 1)
  }

  canRetry(error: ExportError): boolean {
    if (!error.recoverable) return false

    const count = this.errorCounts.get(error.code) || 0
    return count < this.maxRetries
  }

  getRetryDelay(attempt: number): number {
    return Math.min(1000 * Math.pow(2, attempt), 5000)
  }

  getRetryCount(code: ExportErrorCode): number {
    return this.errorCounts.get(code) || 0
  }

  reset(): void {
    this.errorCounts.clear()
  }

  getErrorSummary(): string {
    const summaries: string[] = []
    for (const [code, count] of this.errorCounts.entries()) {
      summaries.push(`${code}: ${count} 次`)
    }
    return summaries.join(', ')
  }
}
