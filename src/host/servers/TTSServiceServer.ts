import express, { Request, Response, NextFunction } from 'express'
import { ILogObj, Logger } from 'tslog'
import * as fs from 'node:fs'
import path from 'node:path'
import { tmpdir } from 'node:os'

export interface TTSServiceConfig {
  gptSoVITSApiUrl: string
  textLang: string
  promptLang: string
  defaultRefAudioPath: string
  defaultPromptText: string
  speedFactor: number
  topK: number
  topP: number
  temperature: number
  mediaType: 'wav' | 'ogg' | 'aac' | 'raw'
  fragmentInterval: number
  gptWeightsPath: string
  sovitsWeightsPath: string
}

export interface CharacterVoiceConfig {
  characterName: string
  refAudioPath: string
  promptText: string
  promptLang: string
}

export interface SynthesizeRequest {
  text: string
  text_lang?: string
  ref_audio_path?: string
  prompt_text?: string
  prompt_lang?: string
  character_name?: string
  speed_factor?: number
  top_k?: number
  top_p?: number
  temperature?: number
  media_type?: string
  gpt_weights?: string
  sovits_weights?: string
}

export interface BatchSynthesizeRequest {
  items: SynthesizeRequest[]
  concurrency?: number
}

export interface SynthesizeResult {
  success: boolean
  duration_ms: number
  audio_base64?: string
  audio_path?: string
  error?: string
}

interface GPTSoVITSRequest {
  text: string
  text_lang: string
  ref_audio_path: string
  aux_ref_audio_paths: string[]
  prompt_text: string
  prompt_lang: string
  top_k: number
  top_p: number
  temperature: number
  text_split_method: string
  batch_size: number
  batch_threshold: number
  split_bucket: boolean
  speed_factor: number
  fragment_interval: number
  seed: number
  media_type: string
  streaming_mode: boolean
  parallel_infer: boolean
  repetition_penalty: number
  gpt_weights?: string
  sovits_weights?: string
}

interface CacheEntry {
  audioBuffer: Buffer
  durationMs: number
  timestamp: number
}

const DEFAULT_CONFIG: TTSServiceConfig = {
  gptSoVITSApiUrl: 'http://127.0.0.1:9880',
  textLang: 'zh',
  promptLang: 'zh',
  defaultRefAudioPath: '',
  defaultPromptText: '',
  speedFactor: 1.0,
  topK: 5,
  topP: 1.0,
  temperature: 1.0,
  mediaType: 'wav',
  fragmentInterval: 0.3,
  gptWeightsPath: '',
  sovitsWeightsPath: ''
}

const DEFAULT_BATCH_CONCURRENCY = 3
const MAX_CACHE_SIZE = 100
const CACHE_TTL_MS = 30 * 60 * 1000
const REQUEST_TIMEOUT_MS = 60000

export class TTSServiceServer {
  private config: TTSServiceConfig
  private characterConfigs: Map<string, CharacterVoiceConfig> = new Map()
  private audioCache: Map<string, CacheEntry> = new Map()
  private readonly app: express.Application
  private server: ReturnType<typeof import('http').createServer> | null = null
  private readonly logger: Logger<ILogObj>
  private readonly port: number
  private readonly host: string
  private readonly tmpDir: string
  private cacheCleanupInterval: ReturnType<typeof setInterval> | null = null

  constructor(
    logger: Logger<ILogObj>,
    config: Partial<TTSServiceConfig> = {},
    port: number = 9882,
    host: string = '127.0.0.1'
  ) {
    this.logger = logger
    this.config = { ...DEFAULT_CONFIG, ...config }
    this.port = port
    this.host = host
    this.tmpDir = path.join(tmpdir(), 'mss-tts-output')
    this.ensureTmpDir()
    this.app = express()
    this.setupMiddleware()
    this.setupRoutes()
    this.startCacheCleanup()
  }

  private ensureTmpDir(): void {
    if (!fs.existsSync(this.tmpDir)) {
      fs.mkdirSync(this.tmpDir, { recursive: true })
    }
  }

  private startCacheCleanup(): void {
    this.cacheCleanupInterval = setInterval(
      () => {
        this.cleanupExpiredCache()
      },
      5 * 60 * 1000
    )
  }

  private cleanupExpiredCache(): void {
    const now = Date.now()
    let cleaned = 0
    for (const [key, entry] of this.audioCache.entries()) {
      if (now - entry.timestamp > CACHE_TTL_MS) {
        this.audioCache.delete(key)
        cleaned++
      }
    }
    if (cleaned > 0) {
      this.logger.info(`[TTS-Service] Cleaned up ${cleaned} expired cache entries`)
    }
  }

  private setupMiddleware(): void {
    this.app.use(express.json({ limit: '50mb' }))

    this.app.use((req: Request, res: Response, next: NextFunction) => {
      this.logger.info(`[TTS-Service] ${req.method} ${req.url}`)
      res.setHeader('Access-Control-Allow-Origin', '*')
      res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
      res.setHeader('Access-Control-Allow-Headers', 'Content-Type')
      if (req.method === 'OPTIONS') {
        res.sendStatus(204)
        return
      }
      next()
    })
  }

  private setupRoutes(): void {
    this.app.get('/health', (_req: Request, res: Response) => {
      res.json({
        status: 'ok',
        service: 'mss-tts-service',
        version: '1.0.0',
        config: {
          gptSoVITSApiUrl: this.config.gptSoVITSApiUrl,
          textLang: this.config.textLang,
          mediaType: this.config.mediaType,
          characterCount: this.characterConfigs.size,
          cacheSize: this.audioCache.size
        }
      })
    })

    this.app.post('/synthesize', async (req: Request, res: Response) => {
      try {
        const request = req.body as SynthesizeRequest
        if (!request.text || typeof request.text !== 'string') {
          res.status(400).json({ success: false, error: 'Missing or invalid required field: text' })
          return
        }
        const result = await this.synthesize(request)
        res.json(result)
      } catch (error) {
        this.logger.error('[TTS-Service] /synthesize error', error)
        res.status(500).json({ success: false, error: 'Internal server error' })
      }
    })

    this.app.post('/synthesize/audio', async (req: Request, res: Response) => {
      let filePath: string | null = null
      try {
        const request = req.body as SynthesizeRequest
        if (!request.text || typeof request.text !== 'string') {
          res.status(400).json({ success: false, error: 'Missing or invalid required field: text' })
          return
        }
        const result = await this.synthesize(request)
        if (!result.success || !result.audio_path) {
          res.status(500).json(result)
          return
        }
        filePath = result.audio_path
        if (!fs.existsSync(filePath)) {
          res.status(404).json({ success: false, error: 'Audio file not found' })
          return
        }
        res.setHeader('Content-Type', 'audio/wav')
        res.setHeader('X-Audio-Duration-Ms', String(result.duration_ms))

        const stream = fs.createReadStream(filePath)
        stream.on('close', () => {
          this.safeDeleteFile(filePath!)
        })
        stream.on('error', (err) => {
          this.logger.error('[TTS-Service] Stream error', err)
          this.safeDeleteFile(filePath!)
        })

        stream.pipe(res)
      } catch (error) {
        this.logger.error('[TTS-Service] /synthesize/audio error', error)
        if (filePath) {
          this.safeDeleteFile(filePath)
        }
        res.status(500).json({ success: false, error: 'Internal server error' })
      }
    })

    this.app.post('/synthesize/batch', async (req: Request, res: Response) => {
      try {
        const request = req.body as BatchSynthesizeRequest
        if (!request.items || !Array.isArray(request.items) || request.items.length === 0) {
          res
            .status(400)
            .json({ success: false, error: 'Missing or invalid required field: items' })
          return
        }

        const concurrency = Math.min(request.concurrency || DEFAULT_BATCH_CONCURRENCY, 5)

        const results: SynthesizeResult[] = await this.processBatch(request.items, concurrency)
        res.json({ success: true, results })
      } catch (error) {
        this.logger.error('[TTS-Service] /synthesize/batch error', error)
        res.status(500).json({ success: false, error: 'Internal server error' })
      }
    })

    this.app.post('/config', (req: Request, res: Response) => {
      try {
        const newConfig = req.body as Partial<TTSServiceConfig>
        this.config = { ...this.config, ...newConfig }
        this.audioCache.clear()
        this.logger.info('[TTS-Service] Config updated, cache cleared')
        res.json({ success: true, config: this.config })
      } catch (error) {
        this.logger.error('[TTS-Service] /config POST error', error)
        res.status(500).json({ success: false, error: 'Internal server error' })
      }
    })

    this.app.get('/config', (_req: Request, res: Response) => {
      res.json(this.config)
    })

    this.app.post('/character', (req: Request, res: Response) => {
      try {
        const charConfig = req.body as CharacterVoiceConfig
        if (!charConfig.characterName || typeof charConfig.characterName !== 'string') {
          res
            .status(400)
            .json({ success: false, error: 'Missing or invalid required field: characterName' })
          return
        }
        this.characterConfigs.set(charConfig.characterName, charConfig)
        this.logger.info(`[TTS-Service] Character registered: ${charConfig.characterName}`)
        res.json({ success: true })
      } catch (error) {
        this.logger.error('[TTS-Service] /character POST error', error)
        res.status(500).json({ success: false, error: 'Internal server error' })
      }
    })

    this.app.get('/characters', (_req: Request, res: Response) => {
      const characters = Array.from(this.characterConfigs.entries()).map(([name, config]) => ({
        name,
        refAudioPath: config.refAudioPath,
        promptLang: config.promptLang
      }))
      res.json({ success: true, characters })
    })

    this.app.delete('/cache', (_req: Request, res: Response) => {
      const count = this.audioCache.size
      this.audioCache.clear()
      this.logger.info(`[TTS-Service] Cache cleared: ${count} entries removed`)
      res.json({ success: true, cleared: count })
    })

    this.app.get('/cache/stats', (_req: Request, res: Response) => {
      let totalSize = 0
      for (const entry of this.audioCache.values()) {
        totalSize += entry.audioBuffer.length
      }
      res.json({
        success: true,
        entries: this.audioCache.size,
        totalSizeBytes: totalSize,
        totalSizeMB: (totalSize / 1024 / 1024).toFixed(2)
      })
    })

    this.app.use((err: Error, _req: Request, res: Response, _next: NextFunction) => {
      this.logger.error('[TTS-Service] Unhandled error', err)
      res.status(500).json({ success: false, error: 'Internal server error' })
    })
  }

  private async processBatch(
    items: SynthesizeRequest[],
    concurrency: number
  ): Promise<SynthesizeResult[]> {
    const results: SynthesizeResult[] = new Array(items.length)

    const executeWithSlot = async (index: number): Promise<void> => {
      try {
        results[index] = await this.synthesize(items[index])
      } catch (error) {
        results[index] = {
          success: false,
          duration_ms: 0,
          error: error instanceof Error ? error.message : String(error)
        }
      }
    }

    const executing: Promise<void>[] = []

    for (let i = 0; i < items.length; i++) {
      const promise = executeWithSlot(i)
      executing.push(promise)

      if (executing.length >= concurrency) {
        await Promise.race(executing)
        for (let j = executing.length - 1; j >= 0; j--) {
          const p = executing[j]
          const settled = await Promise.race([
            p.then(
              () => true,
              () => true
            ),
            Promise.resolve(false)
          ])
          if (settled) {
            executing.splice(j, 1)
          }
        }
      }
    }

    await Promise.all(executing)
    return results
  }

  private getCacheKey(request: SynthesizeRequest): string {
    const params = [
      request.character_name || 'default',
      request.text,
      request.speed_factor || this.config.speedFactor,
      request.top_k || this.config.topK,
      request.top_p || this.config.topP,
      request.temperature || this.config.temperature
    ]
    return params.join(':')
  }

  private async synthesize(request: SynthesizeRequest): Promise<SynthesizeResult> {
    const cacheKey = this.getCacheKey(request)
    const cached = this.audioCache.get(cacheKey)
    if (cached) {
      cached.timestamp = Date.now()
      const outputPath = this.createTempFilePath('cached')
      try {
        await fs.promises.writeFile(outputPath, cached.audioBuffer)
        return {
          success: true,
          duration_ms: cached.durationMs,
          audio_path: outputPath
        }
      } catch (error) {
        this.logger.error('[TTS-Service] Cache write error', error)
      }
    }

    const charConfig = request.character_name
      ? this.characterConfigs.get(request.character_name)
      : undefined

    const refAudioPath =
      request.ref_audio_path || charConfig?.refAudioPath || this.config.defaultRefAudioPath
    const promptText =
      request.prompt_text || charConfig?.promptText || this.config.defaultPromptText
    const promptLang = request.prompt_lang || charConfig?.promptLang || this.config.promptLang

    if (!refAudioPath) {
      return {
        success: false,
        duration_ms: 0,
        error: `No reference audio configured${request.character_name ? ` for character: ${request.character_name}` : ''}`
      }
    }

    const gptRequest: GPTSoVITSRequest = {
      text: request.text,
      text_lang: (request.text_lang || this.config.textLang).toLowerCase(),
      ref_audio_path: refAudioPath,
      aux_ref_audio_paths: [],
      prompt_text: promptText,
      prompt_lang: promptLang.toLowerCase(),
      top_k: request.top_k ?? this.config.topK,
      top_p: request.top_p ?? this.config.topP,
      temperature: request.temperature ?? this.config.temperature,
      text_split_method: 'cut5',
      batch_size: 1,
      batch_threshold: 0.75,
      split_bucket: true,
      speed_factor: request.speed_factor ?? this.config.speedFactor,
      fragment_interval: this.config.fragmentInterval,
      seed: -1,
      media_type: request.media_type || this.config.mediaType,
      streaming_mode: false,
      parallel_infer: true,
      repetition_penalty: 1.35
    }

    const gptWeights = request.gpt_weights || this.config.gptWeightsPath
    if (gptWeights) gptRequest.gpt_weights = gptWeights
    const sovitsWeights = request.sovits_weights || this.config.sovitsWeightsPath
    if (sovitsWeights) gptRequest.sovits_weights = sovitsWeights

    try {
      const response = await fetch(`${this.config.gptSoVITSApiUrl}/tts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(gptRequest),
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS)
      })

      if (!response.ok) {
        const errorData = (await response.json().catch(() => null)) as Record<
          string,
          unknown
        > | null
        const errorMsg =
          (errorData?.message as string) ||
          (errorData?.Exception as string) ||
          `HTTP ${response.status}`
        return { success: false, duration_ms: 0, error: `GPT-SoVITS API error: ${errorMsg}` }
      }

      const audioBuffer = Buffer.from(await response.arrayBuffer())
      if (!audioBuffer || audioBuffer.byteLength === 0) {
        return { success: false, duration_ms: 0, error: 'GPT-SoVITS API returned empty audio' }
      }

      const durationMs = this.calculateWavDuration(audioBuffer)

      this.addToCache(cacheKey, { audioBuffer, durationMs, timestamp: Date.now() })

      const outputPath = this.createTempFilePath()
      await fs.promises.writeFile(outputPath, audioBuffer)

      this.logger.info(
        `[TTS-Service] Synthesized: "${request.text.substring(0, 30)}..." -> ${durationMs}ms, ${(audioBuffer.byteLength / 1024).toFixed(1)} KB`
      )

      return {
        success: true,
        duration_ms: durationMs,
        audio_path: outputPath
      }
    } catch (error) {
      return {
        success: false,
        duration_ms: 0,
        error: `TTS request failed: ${error instanceof Error ? error.message : String(error)}`
      }
    }
  }

  private createTempFilePath(prefix: string = 'tts'): string {
    const timestamp = Date.now()
    const random = Math.random().toString(36).substring(2, 6)
    return path.join(this.tmpDir, `${prefix}-${timestamp}-${random}.wav`)
  }

  private addToCache(key: string, entry: CacheEntry): void {
    if (this.audioCache.size >= MAX_CACHE_SIZE) {
      const oldestKey = this.audioCache.keys().next().value
      if (oldestKey !== undefined) {
        this.audioCache.delete(oldestKey)
      }
    }
    this.audioCache.set(key, entry)
  }

  private safeDeleteFile(filePath: string): void {
    try {
      if (fs.existsSync(filePath)) {
        fs.unlinkSync(filePath)
      }
    } catch (error) {
      this.logger.warn(`[TTS-Service] Failed to delete file: ${filePath}`, error)
    }
  }

  private calculateWavDuration(buffer: Buffer): number {
    if (buffer.byteLength < 44) return 0
    const magic = buffer.readUInt32LE(0)
    if (magic !== 0x46464952) return 0
    const sampleRate = buffer.readUInt32LE(24)
    const bitsPerSample = buffer.readUInt16LE(34)
    const numChannels = buffer.readUInt16LE(22)
    const dataSize = buffer.readUInt32LE(40)
    const byteRate = sampleRate * numChannels * (bitsPerSample / 8)
    if (byteRate === 0) return 0
    return (dataSize / byteRate) * 1000
  }

  updateConfig(config: Partial<TTSServiceConfig>): void {
    this.config = { ...this.config, ...config }
    this.audioCache.clear()
    this.logger.info('[TTS-Service] Config updated externally, cache cleared')
  }

  getConfig(): TTSServiceConfig {
    return { ...this.config }
  }

  start(): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        this.server = this.app.listen(this.port, this.host, () => {
          this.logger.info(`[TTS-Service] Server started on http://${this.host}:${this.port}`)
          this.logger.info(`[TTS-Service] GPT-SoVITS API: ${this.config.gptSoVITSApiUrl}`)
          this.logger.info(
            `[TTS-Service] Endpoints: POST /synthesize, POST /synthesize/batch, POST /config, POST /character`
          )
          resolve()
        })
        this.server.on('error', (err: Error) => {
          this.logger.error('[TTS-Service] Server error', err)
          reject(err)
        })
      } catch (error) {
        reject(error)
      }
    })
  }

  stop(): void {
    if (this.cacheCleanupInterval) {
      clearInterval(this.cacheCleanupInterval)
      this.cacheCleanupInterval = null
    }
    if (this.server) {
      this.server.close()
      this.server = null
      this.logger.info('[TTS-Service] Server stopped')
    }
  }
}
