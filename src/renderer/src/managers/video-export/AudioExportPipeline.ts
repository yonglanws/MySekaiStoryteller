import { ExportLogger } from './ExportLogger'
import type { TTSManager } from '../TTSManager'
import type { SnippetData } from '../../../../common/types/Story'
import type { AudioTimestampEntry, AudioTimestampManifest } from './AudioTimestampManifest'

export interface AudioExportPipelineConfig {
  ttsTimeoutMs: number
  maxRetries: number
}

export interface AudioExportResult {
  success: boolean
  manifest: AudioTimestampManifest | null
  totalDurationMs: number
  trackCount: number
}

export class AudioExportPipeline {
  private readonly logger: ExportLogger = new ExportLogger('AudioExportPipeline')
  private readonly config: Required<AudioExportPipelineConfig>
  private aborted: boolean = false

  constructor(config?: Partial<AudioExportPipelineConfig>) {
    this.config = {
      ttsTimeoutMs: config?.ttsTimeoutMs ?? 30000,
      maxRetries: config?.maxRetries ?? 2
    }
  }

  abort(): void {
    this.aborted = true
    this.logger.info('Audio export pipeline aborted')
  }

  async synthesizeAllAudio(
    snippets: SnippetData[],
    ttsManager: TTSManager,
    onProgress?: (current: number, total: number, message: string) => void
  ): Promise<AudioExportResult> {
    this.aborted = false
    const startTime = performance.now()

    if (!ttsManager.isTTSEnabled()) {
      this.logger.info('TTS disabled, skipping audio synthesis')
      return { success: true, manifest: null, totalDurationMs: 0, trackCount: 0 }
    }

    this.logger.info('Starting audio export pipeline', {
      snippetCount: snippets.length,
      timeout: this.config.ttsTimeoutMs,
      maxRetries: this.config.maxRetries
    })

    const talkSnippets: { index: number; speaker: string; content: string }[] = []
    for (let i = 0; i < snippets.length; i++) {
      if (snippets[i].type === 'Talk') {
        const snippet = snippets[i] as SnippetData & { data?: { speaker: string; content: string } }
        const data =
          snippet.data ||
          ((snippet as Record<string, unknown>).data as
            | { speaker: string; content: string }
            | undefined)
        talkSnippets.push({
          index: i,
          speaker: data?.speaker || '',
          content: data?.content || ''
        })
      }
    }

    this.logger.info(`Audio pipeline: ${talkSnippets.length} Talk snippets to synthesize`)

    const totalTalkCount = talkSnippets.length
    const entries: AudioTimestampEntry[] = []
    let currentTimeMs = 0
    const synthesizedDurations: Map<number, number> = new Map()

    for (let i = 0; i < snippets.length; i++) {
      if (this.aborted) {
        this.logger.info('Audio pipeline aborted')
        break
      }

      const snippet = snippets[i]
      const baseDelayMs = Math.max((snippet.delay || 0) * 1000, 200)
      const ttsDurationMs = synthesizedDurations.get(i) ?? 0
      let snippetDurationMs =
        ttsDurationMs > 0 ? Math.max(baseDelayMs, ttsDurationMs + 80) : baseDelayMs

      if (snippet.type === 'Talk') {
        const talkIndex = talkSnippets.findIndex((t) => t.index === i)
        if (talkIndex >= 0) {
          const talk = talkSnippets[talkIndex]

          ttsManager.setCurrentTime(currentTimeMs)

          const ttsResult = await this.synthesizeWithRetry(
            ttsManager,
            talk,
            talkIndex,
            totalTalkCount
          )

          if (ttsResult && ttsResult.success) {
            synthesizedDurations.set(i, ttsResult.duration)
            snippetDurationMs = Math.max(baseDelayMs, ttsResult.duration + 200)
            const entry: AudioTimestampEntry = {
              snippetIndex: i,
              characterName: talk.speaker,
              text: talk.content,
              startTimeMs: currentTimeMs,
              endTimeMs: currentTimeMs + ttsResult.duration,
              durationMs: ttsResult.duration,
              audioFilePath: `track_${i}`
            }
            entries.push(entry)
            this.logger.info(
              `Audio entry [${i}] "${talk.speaker}": duration=${ttsResult.duration}ms, snippetDuration=${snippetDurationMs}ms, ttsManager audioTracks now: ${ttsManager.getAudioTracks().length}`
            )
          } else {
            this.logger.warn(`Audio synthesis failed for snippet ${i}, using silence`)
            synthesizedDurations.set(i, 0)
          }
        }
      }

      currentTimeMs += snippetDurationMs
      const completed = Math.min(talkSnippets.filter((t) => t.index <= i).length, totalTalkCount)
      onProgress?.(completed, totalTalkCount, `正在合成语音 ${completed}/${totalTalkCount}`)
    }

    const totalDurationMs = currentTimeMs
    const trackCount = entries.length

    const manifest: AudioTimestampManifest = {
      entries,
      totalAudioDurationMs: entries.reduce((sum, e) => sum + e.durationMs, 0),
      totalStoryDurationMs: totalDurationMs
    }

    const elapsed = performance.now() - startTime
    this.logger.info('Audio export pipeline completed', {
      trackCount,
      totalDurationMs,
      elapsed: `${(elapsed / 1000).toFixed(1)}s`
    })

    return {
      success: true,
      manifest,
      totalDurationMs,
      trackCount
    }
  }

  private async synthesizeWithRetry(
    ttsManager: TTSManager,
    talk: { speaker: string; content: string },
    index: number,
    _total: number
  ): Promise<{ success: boolean; duration: number } | null> {
    let lastError: Error | null = null

    for (let attempt = 0; attempt <= this.config.maxRetries; attempt++) {
      if (this.aborted) return null

      try {
        const result = await this.synthesizeWithTimeout(ttsManager, talk.content, talk.speaker)
        return result
      } catch (error) {
        lastError = error instanceof Error ? error : new Error(String(error))
        this.logger.warn(
          `TTS attempt ${attempt + 1}/${this.config.maxRetries + 1} failed for [${index}]: ${lastError.message}`
        )
        if (attempt < this.config.maxRetries) {
          await this.sleep(500 * (attempt + 1))
        }
      }
    }

    this.logger.error(
      `TTS failed for [${index}] after ${this.config.maxRetries + 1} attempts: ${lastError?.message}`
    )
    return null
  }

  private async synthesizeWithTimeout(
    ttsManager: TTSManager,
    content: string,
    characterName: string
  ): Promise<{ success: boolean; duration: number }> {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(new Error(`TTS synthesis timeout (${this.config.ttsTimeoutMs}ms)`))
      }, this.config.ttsTimeoutMs)

      ttsManager
        .translateAndSynthesize(content, characterName)
        .then((result) => {
          clearTimeout(timer)
          resolve(result)
        })
        .catch((error) => {
          clearTimeout(timer)
          reject(error)
        })
    })
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
  }
}
