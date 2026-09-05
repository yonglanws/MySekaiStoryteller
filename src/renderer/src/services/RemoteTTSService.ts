import getSubLogger from '../utils/Logger'

const logger = getSubLogger('RemoteTTSService')

export interface RemoteTTSConfig {
  enabled: boolean
  serviceUrl: string
  connectTimeout: number
  requestTimeout: number
  maxRetries: number
  retryDelay: number
}

export interface RemoteSynthesizeResult {
  success: boolean
  duration_ms: number
  audioBuffer?: ArrayBuffer
  audioPath?: string
  error?: string
}

interface SynthesizeParams {
  text: string
  text_lang?: string
  character_name?: string
  ref_audio_path?: string
  prompt_text?: string
  prompt_lang?: string
  speed_factor?: number
}

const DEFAULT_REMOTE_CONFIG: RemoteTTSConfig = {
  enabled: true,
  serviceUrl: 'http://127.0.0.1:9882',
  connectTimeout: 5000,
  requestTimeout: 60000,
  maxRetries: 2,
  retryDelay: 1000
}

export class RemoteTTSService {
  private config: RemoteTTSConfig
  private healthCheckInterval: ReturnType<typeof setInterval> | null = null
  private _isAvailable: boolean = false
  private availabilityCheckPromise: Promise<boolean> | null = null

  constructor(config: Partial<RemoteTTSConfig> = {}) {
    this.config = { ...DEFAULT_REMOTE_CONFIG, ...config }
  }

  get isAvailable(): boolean {
    return this._isAvailable
  }

  get serviceUrl(): string {
    return this.config.serviceUrl
  }

  updateConfig(config: Partial<RemoteTTSConfig>): void {
    this.config = { ...this.config, ...config }
    this._isAvailable = false
  }

  async checkHealth(): Promise<{
    available: boolean
    info?: Record<string, unknown>
    error?: string
  }> {
    try {
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), this.config.connectTimeout)

      const response = await fetch(`${this.config.serviceUrl}/health`, {
        signal: controller.signal
      })
      clearTimeout(timeoutId)

      if (!response.ok) {
        this._isAvailable = false
        return { available: false, error: `HTTP ${response.status}` }
      }
      const info = (await response.json()) as Record<string, unknown>
      this._isAvailable = true
      return { available: true, info }
    } catch (error) {
      this._isAvailable = false
      return {
        available: false,
        error: error instanceof Error ? error.message : String(error)
      }
    }
  }

  private async ensureAvailable(): Promise<boolean> {
    if (this._isAvailable) {
      return true
    }

    if (this.availabilityCheckPromise) {
      return this.availabilityCheckPromise
    }

    this.availabilityCheckPromise = this.checkHealth()
      .then((result) => {
        this.availabilityCheckPromise = null
        return result.available
      })
      .catch(() => {
        this.availabilityCheckPromise = null
        return false
      })

    return this.availabilityCheckPromise
  }

  startHealthCheck(intervalMs: number = 30000): void {
    this.stopHealthCheck()
    this.checkHealth().catch((err) => {
      logger.warn('TTS health check failed', err instanceof Error ? err.message : err)
    })
    this.healthCheckInterval = setInterval(() => {
      this.checkHealth().catch((err) => {
        logger.warn('TTS health check failed', err instanceof Error ? err.message : err)
      })
    }, intervalMs)
  }

  stopHealthCheck(): void {
    if (this.healthCheckInterval) {
      clearInterval(this.healthCheckInterval)
      this.healthCheckInterval = null
    }
  }

  private async fetchWithRetry(
    url: string,
    options: RequestInit,
    retries: number = this.config.maxRetries
  ): Promise<Response> {
    try {
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), this.config.requestTimeout)

      const response = await fetch(url, {
        ...options,
        signal: controller.signal
      })
      clearTimeout(timeoutId)
      return response
    } catch (error) {
      if (retries > 0) {
        logger.warn(`Request failed, retrying... (${retries} retries left)`)
        await this.delay(this.config.retryDelay)
        return this.fetchWithRetry(url, options, retries - 1)
      }
      throw error
    }
  }

  private delay(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
  }

  async synthesize(params: SynthesizeParams): Promise<RemoteSynthesizeResult> {
    const available = await this.ensureAvailable()
    if (!available) {
      return {
        success: false,
        duration_ms: 0,
        error: `TTS Service unavailable at ${this.config.serviceUrl}`
      }
    }

    try {
      const response = await this.fetchWithRetry(`${this.config.serviceUrl}/synthesize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params)
      })

      if (!response.ok) {
        const errorData = (await response.json().catch(() => null)) as Record<
          string,
          unknown
        > | null
        return {
          success: false,
          duration_ms: 0,
          error: (errorData?.error as string) || `HTTP ${response.status}`
        }
      }

      const result = (await response.json()) as RemoteSynthesizeResult & { audio_path?: string }

      if (result.success && result.audio_path) {
        try {
          const audioResponse = await fetch(`file://${result.audio_path}`)
          if (audioResponse.ok) {
            result.audioBuffer = await audioResponse.arrayBuffer()
          }
        } catch {
          logger.warn(`Cannot fetch audio file directly, path: ${result.audio_path}`)
        }
      }

      return result
    } catch (error) {
      this._isAvailable = false
      return {
        success: false,
        duration_ms: 0,
        error: `Remote TTS request failed: ${error instanceof Error ? error.message : String(error)}`
      }
    }
  }

  async synthesizeAndGetAudio(params: SynthesizeParams): Promise<RemoteSynthesizeResult> {
    const available = await this.ensureAvailable()
    if (!available) {
      return {
        success: false,
        duration_ms: 0,
        error: `TTS Service unavailable at ${this.config.serviceUrl}`
      }
    }

    try {
      const response = await this.fetchWithRetry(`${this.config.serviceUrl}/synthesize/audio`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params)
      })

      if (!response.ok) {
        const errorData = (await response.json().catch(() => null)) as Record<
          string,
          unknown
        > | null
        return {
          success: false,
          duration_ms: 0,
          error: (errorData?.error as string) || `HTTP ${response.status}`
        }
      }

      const durationMs = parseInt(response.headers.get('X-Audio-Duration-Ms') || '0', 10)
      const audioBuffer = await response.arrayBuffer()

      return {
        success: true,
        duration_ms: durationMs || this.calculateWavDuration(audioBuffer),
        audioBuffer
      }
    } catch (error) {
      this._isAvailable = false
      return {
        success: false,
        duration_ms: 0,
        error: `Remote TTS audio request failed: ${error instanceof Error ? error.message : String(error)}`
      }
    }
  }

  async registerCharacter(params: {
    characterName: string
    refAudioPath: string
    promptText: string
    promptLang: string
    gptWeightsPath?: string
    sovitsWeightsPath?: string
  }): Promise<boolean> {
    try {
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), this.config.connectTimeout)

      const response = await fetch(`${this.config.serviceUrl}/character`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
        signal: controller.signal
      })
      clearTimeout(timeoutId)
      return response.ok
    } catch {
      return false
    }
  }

  async updateServiceConfig(config: Record<string, unknown>): Promise<boolean> {
    try {
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), this.config.connectTimeout)

      const response = await fetch(`${this.config.serviceUrl}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
        signal: controller.signal
      })
      clearTimeout(timeoutId)
      return response.ok
    } catch {
      return false
    }
  }

  async getCacheStats(): Promise<{ entries: number; totalSizeMB: string } | null> {
    try {
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), this.config.connectTimeout)

      const response = await fetch(`${this.config.serviceUrl}/cache/stats`, {
        signal: controller.signal
      })
      clearTimeout(timeoutId)

      if (response.ok) {
        const data = await response.json()
        return {
          entries: data.entries,
          totalSizeMB: data.totalSizeMB
        }
      }
      return null
    } catch {
      return null
    }
  }

  async clearCache(): Promise<boolean> {
    try {
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), this.config.connectTimeout)

      const response = await fetch(`${this.config.serviceUrl}/cache`, {
        method: 'DELETE',
        signal: controller.signal
      })
      clearTimeout(timeoutId)
      return response.ok
    } catch {
      return false
    }
  }

  private calculateWavDuration(buffer: ArrayBuffer): number {
    if (buffer.byteLength < 44) return 0
    const view = new DataView(buffer)
    const magic = view.getUint32(0, true)
    if (magic !== 0x46464952) return 0
    const sampleRate = view.getUint32(24, true)
    const bitsPerSample = view.getUint16(34, true)
    const numChannels = view.getUint16(22, true)
    const dataSize = view.getUint32(40, true)
    const byteRate = sampleRate * numChannels * (bitsPerSample / 8)
    if (byteRate === 0) return 0
    return (dataSize / byteRate) * 1000
  }

  dispose(): void {
    this.stopHealthCheck()
    this._isAvailable = false
  }
}
