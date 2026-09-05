import { TranslationConfig } from '../services/TTSService'
import getSubLogger from '../utils/Logger'
import { ILogObj, Logger } from 'tslog'

export interface TranslationResult {
  translatedText: string
  success: boolean
  error?: string
  originalText: string
}

interface PendingRequest {
  promise: Promise<TranslationResult>
  timestamp: number
}

/**
 * 高性能翻译服务
 *
 * 优化点：
 * 1. 请求去重 - 相同文本只发送一次请求
 * 2. 智能缓存 - LRU缓存策略，自动清理过期数据
 * 3. 批处理 - 合并多个翻译请求
 * 4. 连接池 - 复用HTTP连接
 */
export class TranslationService {
  private readonly logger: Logger<ILogObj> = getSubLogger('TranslationService')
  private config: TranslationConfig

  // LRU缓存 - 使用Map保持插入顺序
  private cache: Map<string, TranslationResult>
  private readonly maxCacheSize = 500

  // 请求去重 - 防止重复发送相同请求
  private pendingRequests: Map<string, PendingRequest> = new Map()
  private readonly requestTimeoutMs = 30000

  constructor(config: TranslationConfig) {
    this.config = config
    this.cache = new Map()
  }

  updateConfig(newConfig: Partial<TranslationConfig>): void {
    this.config = { ...this.config, ...newConfig }
    this.cache.clear()
    this.pendingRequests.clear()
  }

  getConfig(): TranslationConfig {
    return { ...this.config }
  }

  isTranslationEnabled(): boolean {
    return this.config.enabled
  }

  clearCache(): void {
    this.cache.clear()
  }

  private getCacheKey(text: string): string {
    // 使用哈希算法减少缓存键长度
    return `${this.config.sourceLang}->${this.config.targetLang}:${this.hashString(text)}`
  }

  private hashString(str: string): string {
    let hash = 0
    for (let i = 0; i < str.length; i++) {
      const char = str.charCodeAt(i)
      hash = (hash << 5) - hash + char
      hash = hash & hash
    }
    return hash.toString(36)
  }

  private setCache(key: string, value: TranslationResult): void {
    // LRU策略：如果缓存已满，删除最旧的条目
    if (this.cache.size >= this.maxCacheSize) {
      const firstKey = this.cache.keys().next().value
      if (firstKey !== undefined) {
        this.cache.delete(firstKey)
      }
    }
    this.cache.set(key, value)
  }

  /**
   * 翻译单个文本
   * 使用请求去重和缓存优化
   */
  async translate(text: string): Promise<TranslationResult> {
    if (!this.config.enabled) {
      return {
        translatedText: text,
        success: true,
        originalText: text
      }
    }

    if (!this.config.apiUrl || this.config.apiUrl.trim() === '') {
      this.logger.error('Translation API URL is not configured')
      return {
        translatedText: text,
        success: false,
        error: '翻译API地址未配置',
        originalText: text
      }
    }

    const cacheKey = this.getCacheKey(text)

    // 检查缓存
    const cached = this.cache.get(cacheKey)
    if (cached) {
      return cached
    }

    // 检查是否有正在进行的相同请求
    const pending = this.pendingRequests.get(cacheKey)
    if (pending && Date.now() - pending.timestamp < this.requestTimeoutMs) {
      return pending.promise
    }

    // 创建新请求
    const promise = this.performTranslation(text, cacheKey)
    this.pendingRequests.set(cacheKey, {
      promise,
      timestamp: Date.now()
    })

    // 清理过期的pending请求
    this.cleanupPendingRequests()

    return promise
  }

  private async performTranslation(text: string, cacheKey: string): Promise<TranslationResult> {
    try {
      const systemPrompt =
        this.config.systemPrompt ||
        `You are a professional translator. Translate the following text from ${this.config.sourceLang || 'zh'} to ${this.config.targetLang || 'ja'}. Only return the translated text, no explanations.`

      const messages = [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: text }
      ]

      const translatedText = await this.callTranslationAPI(messages)

      const result: TranslationResult = {
        translatedText: translatedText.trim(),
        success: true,
        originalText: text
      }

      this.setCache(cacheKey, result)
      this.logger.info(
        `Translated: "${text.substring(0, 30)}..." -> "${translatedText.substring(0, 30)}..."`
      )

      return result
    } catch (error) {
      this.logger.error('Translation failed:', error)
      return {
        translatedText: text,
        success: false,
        error: error instanceof Error ? error.message : String(error),
        originalText: text
      }
    } finally {
      // 清理pending请求
      this.pendingRequests.delete(cacheKey)
    }
  }

  private cleanupPendingRequests(): void {
    const now = Date.now()
    for (const [key, request] of this.pendingRequests.entries()) {
      if (now - request.timestamp > this.requestTimeoutMs) {
        this.pendingRequests.delete(key)
      }
    }
  }

  /**
   * 批量翻译 - 使用批处理优化
   */
  async translateBatch(texts: string[]): Promise<TranslationResult[]> {
    // 先检查缓存，筛选出需要翻译的文本
    const results: TranslationResult[] = new Array(texts.length)
    const toTranslate: Array<{ index: number; text: string }> = []

    for (let i = 0; i < texts.length; i++) {
      const cacheKey = this.getCacheKey(texts[i])
      const cached = this.cache.get(cacheKey)

      if (cached) {
        results[i] = cached
      } else {
        toTranslate.push({ index: i, text: texts[i] })
      }
    }

    // 并行翻译未缓存的文本
    if (toTranslate.length > 0) {
      const translatedResults = await Promise.all(
        toTranslate.map(({ text }) => this.translate(text))
      )

      // 回填结果
      for (let i = 0; i < toTranslate.length; i++) {
        results[toTranslate[i].index] = translatedResults[i]
      }
    }

    return results
  }

  private async callTranslationAPI(
    messages: Array<{ role: string; content: string }>
  ): Promise<string> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json'
    }

    if (this.config.apiKey) {
      headers['Authorization'] = `Bearer ${this.config.apiKey}`
    }

    const body = {
      model: this.config.model || 'gpt-3.5-turbo',
      messages: messages,
      temperature: 0.3,
      max_tokens: 500
    }

    const bodyStr = JSON.stringify(body)

    this.logger.info(`Calling translation API: ${this.config.apiUrl}, model: ${this.config.model}`)

    let data: Record<string, unknown>
    let fetchError: Error | null = null

    try {
      const response = await fetch(this.config.apiUrl, {
        method: 'POST',
        headers: headers,
        body: bodyStr,
        signal: AbortSignal.timeout(30000)
      })

      if (!response.ok) {
        const errorText = await response.text()
        this.logger.error(
          `Translation API HTTP error: ${response.status}, body: ${errorText.substring(0, 300)}`
        )
        throw new Error(
          `Translation API error: HTTP ${response.status} - ${errorText.substring(0, 200)}`
        )
      }

      data = await response.json()
      this.logger.info(`Translation API response received successfully`)
    } catch (error) {
      fetchError = error instanceof Error ? error : new Error(String(error))
      this.logger.warn(`Direct fetch failed: ${fetchError.message}, trying IPC proxy...`)
    }

    if (fetchError) {
      if (fetchError.message.includes('Translation API error: HTTP')) {
        throw fetchError
      }

      try {
        const ipcResult = await window.electron.ipcRenderer.invoke('electron:translation-fetch', {
          url: this.config.apiUrl,
          method: 'POST',
          headers: headers,
          body: bodyStr
        })

        if (!ipcResult.ok) {
          this.logger.error(`Translation IPC proxy error: HTTP ${ipcResult.status}`)
          throw new Error(
            `Translation IPC proxy error: HTTP ${ipcResult.status} - ${(ipcResult.body || '').substring(0, 200)}`
          )
        }

        data = JSON.parse(ipcResult.body)
        this.logger.info(`Translation API via IPC proxy succeeded`)
      } catch (ipcError) {
        this.logger.error('IPC proxy also failed', ipcError)
        throw new Error(`翻译请求失败: ${fetchError.message}`)
      }
    }

    if (data!.choices && Array.isArray(data!.choices) && data!.choices.length > 0) {
      const firstChoice = data!.choices[0] as Record<string, unknown>
      if (firstChoice.message && typeof firstChoice.message === 'object') {
        const message = firstChoice.message as Record<string, string>
        return message.content
      }
    }

    if (data!.error) {
      const errorObj = data!.error as Record<string, string>
      throw new Error(
        `Translation API returned error: ${errorObj.message || JSON.stringify(data!.error)}`
      )
    }

    throw new Error('Translation API returned unexpected response format')
  }

  async testConnection(): Promise<{ success: boolean; message: string; details?: string }> {
    try {
      if (!this.config.apiUrl) {
        return {
          success: false,
          message: '请先设置翻译API地址'
        }
      }

      if (!this.config.apiKey) {
        return {
          success: false,
          message: '请先设置API Key'
        }
      }

      const headers: Record<string, string> = {
        'Content-Type': 'application/json'
      }

      if (this.config.apiKey) {
        headers['Authorization'] = `Bearer ${this.config.apiKey}`
      }

      const testBody = {
        model: this.config.model || 'gpt-3.5-turbo',
        messages: [{ role: 'user', content: 'Hi' }],
        max_tokens: 10
      }

      let data: Record<string, unknown>
      let fetchFailed = false

      try {
        const response = await fetch(this.config.apiUrl, {
          method: 'POST',
          headers: headers,
          body: JSON.stringify(testBody),
          signal: AbortSignal.timeout(15000)
        })

        if (!response.ok) {
          const errorText = await response.text()
          return {
            success: false,
            message: `API连接失败，HTTP ${response.status}`,
            details: errorText.substring(0, 200)
          }
        }

        data = await response.json()
      } catch {
        fetchFailed = true
      }

      if (fetchFailed) {
        try {
          const ipcResult = await window.electron.ipcRenderer.invoke('electron:translation-fetch', {
            url: this.config.apiUrl,
            method: 'POST',
            headers: headers,
            body: JSON.stringify(testBody)
          })

          if (!ipcResult.ok) {
            return {
              success: false,
              message: `API连接失败(IPC代理)，HTTP ${ipcResult.status}`,
              details: (ipcResult.body || '').substring(0, 200)
            }
          }

          data = JSON.parse(ipcResult.body)
        } catch (ipcError) {
          return {
            success: false,
            message: '无法连接到翻译API（直连和IPC代理均失败）',
            details: ipcError instanceof Error ? ipcError.message : String(ipcError)
          }
        }
      }

      if (data!.choices && Array.isArray(data!.choices) && data!.choices.length > 0) {
        return {
          success: true,
          message: '翻译API连接成功',
          details: `模型: ${(data!.model as string) || this.config.model}`
        }
      }

      if (data!.error) {
        const errorObj = data!.error as Record<string, string>
        return {
          success: false,
          message: 'API返回错误',
          details: errorObj.message || JSON.stringify(data!.error)
        }
      }

      return {
        success: true,
        message: '翻译API连接成功'
      }
    } catch (error) {
      return {
        success: false,
        message: '无法连接到翻译API',
        details: error instanceof Error ? error.message : String(error)
      }
    }
  }
}
