import { ILogObj, Logger } from 'tslog'
import getSubLogger from '../utils/Logger'

export interface TTSConfig {
  enabled: boolean
  apiBaseUrl: string
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

export interface TranslationConfig {
  enabled: boolean
  apiType: 'openai' | 'deepseek' | 'claude' | 'custom'
  apiUrl: string
  apiKey: string
  model: string
  sourceLang: string
  targetLang: string
  systemPrompt: string
}

export interface BGMConfig {
  enabled: boolean
  path: string
  volume: number
}

export interface TTSRequest {
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

export interface CharacterVoiceConfig {
  characterName: string
  refAudioPath: string
  promptText: string
  promptLang: string
  gptWeightsPath?: string
  sovitsWeightsPath?: string
}

export const DEFAULT_TTS_CONFIG: TTSConfig = {
  enabled: false,
  apiBaseUrl: 'http://127.0.0.1:9880',
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

export interface TTSResult {
  audioBuffer: ArrayBuffer
  duration: number
  success: boolean
  error?: string
}

interface CacheEntry {
  result: TTSResult
  timestamp: number
}

interface Dialogue {
  text: string
  characterName: string
}

const MAX_CACHE_SIZE = 50
const CACHE_TTL_MS = 30 * 60 * 1000
const REQUEST_TIMEOUT_MS = 30000
const TEST_TIMEOUT_MS = 15000

export class TTSService {
  private readonly logger: Logger<ILogObj>
  private config: TTSConfig
  private characterConfigs: Map<string, CharacterVoiceConfig>
  private audioCache: Map<string, CacheEntry>
  private audioContext: AudioContext | null = null

  constructor(config: TTSConfig) {
    this.config = config
    this.characterConfigs = new Map()
    this.audioCache = new Map()
    this.logger = getSubLogger('TTSService')
  }

  updateConfig(config: Partial<TTSConfig>): void {
    this.config = { ...this.config, ...config }
  }

  setCharacterVoice(characterName: string, voiceConfig: CharacterVoiceConfig): void {
    this.characterConfigs.set(characterName, voiceConfig)
  }

  getCharacterVoice(characterName: string): CharacterVoiceConfig | undefined {
    return this.characterConfigs.get(characterName)
  }

  clearCache(): void {
    this.audioCache.clear()
  }

  private getCacheKey(text: string, characterName: string, speedFactor?: number): string {
    return `${characterName}:${speedFactor ?? this.config.speedFactor}:${text}`
  }

  private addToCache(key: string, result: TTSResult): void {
    if (this.audioCache.size >= MAX_CACHE_SIZE) {
      const oldestKey = this.audioCache.keys().next().value
      if (oldestKey !== undefined) {
        this.audioCache.delete(oldestKey)
      }
    }
    this.audioCache.set(key, { result, timestamp: Date.now() })
  }

  private cleanupExpiredCache(): void {
    const now = Date.now()
    for (const [key, entry] of this.audioCache.entries()) {
      if (now - entry.timestamp > CACHE_TTL_MS) {
        this.audioCache.delete(key)
      }
    }
  }

  async synthesizeSpeech(
    text: string,
    characterName: string,
    speedFactor?: number
  ): Promise<TTSResult> {
    this.cleanupExpiredCache()

    const cacheKey = this.getCacheKey(text, characterName, speedFactor)
    const cached = this.audioCache.get(cacheKey)
    if (cached) {
      cached.timestamp = Date.now()
      return cached.result
    }

    if (!this.config.enabled) {
      return {
        audioBuffer: new ArrayBuffer(0),
        duration: 0,
        success: false,
        error: 'TTS is not enabled'
      }
    }

    const charConfig = this.characterConfigs.get(characterName)
    const refAudioPath = charConfig?.refAudioPath || this.config.defaultRefAudioPath
    const promptText = charConfig?.promptText || this.config.defaultPromptText
    const promptLang = charConfig?.promptLang || this.config.promptLang

    if (!refAudioPath) {
      return {
        audioBuffer: new ArrayBuffer(0),
        duration: 0,
        success: false,
        error: `No reference audio configured for character: ${characterName}`
      }
    }

    const request: TTSRequest = {
      text: text,
      text_lang: this.config.textLang.toLowerCase(),
      ref_audio_path: refAudioPath,
      aux_ref_audio_paths: [],
      prompt_text: promptText,
      prompt_lang: promptLang.toLowerCase(),
      top_k: this.config.topK,
      top_p: this.config.topP,
      temperature: this.config.temperature,
      text_split_method: 'cut5',
      batch_size: 1,
      batch_threshold: 0.75,
      split_bucket: true,
      speed_factor: speedFactor ?? this.config.speedFactor,
      fragment_interval: this.config.fragmentInterval,
      seed: -1,
      media_type: this.config.mediaType,
      streaming_mode: false,
      parallel_infer: true,
      repetition_penalty: 1.35
    }

    if (charConfig?.gptWeightsPath || this.config.gptWeightsPath) {
      request.gpt_weights = charConfig?.gptWeightsPath || this.config.gptWeightsPath
    }
    if (charConfig?.sovitsWeightsPath || this.config.sovitsWeightsPath) {
      request.sovits_weights = charConfig?.sovitsWeightsPath || this.config.sovitsWeightsPath
    }

    try {
      const audioBuffer = await this.fetchTTS(request)

      if (!audioBuffer || audioBuffer.byteLength === 0) {
        return {
          audioBuffer: new ArrayBuffer(0),
          duration: 0,
          success: false,
          error: 'TTS API returned empty audio data'
        }
      }

      this.logger.info(`TTS API returned audio: ${audioBuffer.byteLength} bytes`)

      const duration = await this.calculateAudioDuration(audioBuffer)

      this.logger.info(`Calculated audio duration: ${duration}ms`)

      const result: TTSResult = {
        audioBuffer,
        duration,
        success: true
      }

      this.addToCache(cacheKey, result)
      return result
    } catch (error) {
      return {
        audioBuffer: new ArrayBuffer(0),
        duration: 0,
        success: false,
        error: `TTS request failed: ${error instanceof Error ? error.message : String(error)}`
      }
    }
  }

  private async fetchTTS(request: TTSRequest): Promise<ArrayBuffer> {
    try {
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)

      const response = await fetch(`${this.config.apiBaseUrl}/tts`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(request),
        signal: controller.signal
      })
      clearTimeout(timeoutId)

      if (!response.ok) {
        const errorData = await response.json().catch(() => null)
        const errorMsg = errorData?.message || errorData?.Exception || `HTTP ${response.status}`
        throw new Error(`TTS API error: ${errorMsg}`)
      }

      return await response.arrayBuffer()
    } catch (fetchError) {
      if (fetchError instanceof Error && fetchError.name === 'AbortError') {
        throw new Error('TTS request timed out')
      }

      this.logger.warn(
        `Direct fetch failed, trying IPC proxy: ${fetchError instanceof Error ? fetchError.message : String(fetchError)}`
      )

      const ipcResult = await Promise.race([
        window.electron.ipcRenderer.invoke('electron:tts-fetch', {
          url: `${this.config.apiBaseUrl}/tts`,
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify(request)
        }),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error('TTS IPC proxy timed out')), REQUEST_TIMEOUT_MS)
        )
      ])

      if (!ipcResult.ok) {
        throw new Error(`TTS IPC error: HTTP ${ipcResult.status}`)
      }

      return ipcResult.body
    }
  }

  private async calculateAudioDuration(audioBuffer: ArrayBuffer): Promise<number> {
    if (audioBuffer.byteLength < 44) {
      return 0
    }

    const view = new DataView(audioBuffer)
    if (view.getUint32(0, true) === 0x46464952) {
      const sampleRate = view.getUint32(24, true)
      const dataSize = view.getUint32(40, true)
      const bitsPerSample = view.getUint16(34, true)
      const numChannels = view.getUint16(22, true)

      const byteRate = sampleRate * numChannels * (bitsPerSample / 8)
      if (byteRate === 0) {
        return 0
      }

      return (dataSize / byteRate) * 1000
    }

    try {
      if (!this.audioContext) {
        this.audioContext = new AudioContext()
      }
      const decoded = await this.audioContext.decodeAudioData(audioBuffer.slice(0))
      return decoded.duration * 1000
    } catch {
      return 0
    }
  }

  async synthesizeBatch(
    dialogues: Dialogue[],
    concurrency: number = 3
  ): Promise<Map<string, TTSResult>> {
    const results = new Map<string, TTSResult>()
    const executing: Promise<void>[] = []

    for (let i = 0; i < dialogues.length; i++) {
      const dialogue = dialogues[i]
      const promise = this.synthesizeSpeech(dialogue.text, dialogue.characterName).then(
        (result) => {
          const cacheKey = this.getCacheKey(dialogue.text, dialogue.characterName)
          results.set(cacheKey, result)
        }
      )
      executing.push(promise)

      if (executing.length >= concurrency) {
        await Promise.race(executing)
        const index = executing.findIndex((p) => p === promise)
        if (index > -1) {
          executing.splice(index, 1)
        }
      }
    }

    await Promise.all(executing)
    return results
  }

  async testConnection(): Promise<{ success: boolean; message: string; details?: string }> {
    const refAudioPath = this.config.defaultRefAudioPath || 'audio_ref.wav'
    const promptText = this.config.defaultPromptText || '测试'
    const promptLang = this.config.promptLang || 'zh'
    const textLang = this.config.textLang || 'zh'

    const testRequest: TTSRequest = {
      text: '测试',
      text_lang: textLang.toLowerCase(),
      ref_audio_path: refAudioPath,
      aux_ref_audio_paths: [],
      prompt_text: promptText,
      prompt_lang: promptLang.toLowerCase(),
      top_k: this.config.topK,
      top_p: this.config.topP,
      temperature: this.config.temperature,
      text_split_method: 'cut5',
      batch_size: 1,
      batch_threshold: 0.75,
      split_bucket: true,
      speed_factor: this.config.speedFactor,
      fragment_interval: this.config.fragmentInterval,
      seed: -1,
      media_type: this.config.mediaType,
      streaming_mode: false,
      parallel_infer: true,
      repetition_penalty: 1.35
    }

    if (this.config.gptWeightsPath) {
      testRequest.gpt_weights = this.config.gptWeightsPath
    }
    if (this.config.sovitsWeightsPath) {
      testRequest.sovits_weights = this.config.sovitsWeightsPath
    }

    try {
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), TEST_TIMEOUT_MS)

      const response = await fetch(`${this.config.apiBaseUrl}/tts`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(testRequest),
        signal: controller.signal
      })
      clearTimeout(timeoutId)

      if (response.ok) {
        const audioData = await response.arrayBuffer()
        if (audioData.byteLength > 0) {
          return {
            success: true,
            message: 'TTS服务连接成功',
            details: `GPT-SoVITS API 正常响应，音频大小: ${(audioData.byteLength / 1024).toFixed(1)} KB`
          }
        }
        return {
          success: true,
          message: 'TTS服务连接成功',
          details: 'GPT-SoVITS API 响应正常（音频数据为空，请检查参考音频路径配置）'
        }
      }

      if (response.status === 400) {
        const errorData = await response.json().catch(() => null)
        const errorMsg = errorData?.message || errorData?.Exception || ''
        return {
          success: false,
          message: 'TTS服务参数错误',
          details: `HTTP 400: ${errorMsg || '请检查参考音频路径和提示文本配置是否正确'}`
        }
      }

      return {
        success: false,
        message: `连接异常，HTTP ${response.status}`
      }
    } catch (fetchError) {
      this.logger.warn(
        `Direct fetch failed in test, trying IPC: ${fetchError instanceof Error ? fetchError.message : String(fetchError)}`
      )

      try {
        const ipcResult = await window.electron.ipcRenderer.invoke('electron:tts-fetch', {
          url: `${this.config.apiBaseUrl}/tts`,
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify(testRequest)
        })

        if (ipcResult.ok) {
          const audioSize = ipcResult.body?.byteLength ?? 0
          return {
            success: true,
            message: 'TTS服务连接成功',
            details: `GPT-SoVITS API 正常响应（通过IPC代理），音频大小: ${(audioSize / 1024).toFixed(1)} KB`
          }
        }

        if (ipcResult.status === 400) {
          return {
            success: false,
            message: 'TTS服务参数错误',
            details: `HTTP 400: 请检查参考音频路径和提示文本配置是否正确`
          }
        }

        return {
          success: false,
          message: `连接失败，HTTP ${ipcResult.status}`
        }
      } catch (ipcError) {
        return {
          success: false,
          message: `无法连接到TTS服务`,
          details: ipcError instanceof Error ? ipcError.message : String(ipcError)
        }
      }
    }
  }

  getConfig(): TTSConfig {
    return { ...this.config }
  }

  dispose(): void {
    if (this.audioContext) {
      this.audioContext.close().catch((err) => {
        this.logger.warn('AudioContext close error', err instanceof Error ? err.message : err)
      })
      this.audioContext = null
    }
    this.clearCache()
  }
}
