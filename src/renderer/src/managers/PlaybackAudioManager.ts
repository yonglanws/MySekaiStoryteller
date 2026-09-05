import { TTSManager } from './TTSManager'
import getSubLogger from '../utils/Logger'
import { ILogObj, Logger } from 'tslog'
import { builtinResourceUrl } from '../utils/ResourceUrl'

export class PlaybackAudioManager {
  private readonly logger: Logger<ILogObj> = getSubLogger('PlaybackAudioManager')
  private audioContext: AudioContext | null = null
  private bgmSource: AudioBufferSourceNode | null = null
  private bgmGainNode: GainNode | null = null
  private ttsGainNode: GainNode | null = null
  private ttsManager: TTSManager
  private bgmVolume: number = 0.2
  private ttsVolume: number = 0.8
  private isBGMPlaying: boolean = false
  private bgmBuffer: AudioBuffer | null = null
  private currentTTSSource: AudioBufferSourceNode | null = null

  constructor(ttsManager: TTSManager) {
    this.ttsManager = ttsManager
  }

  private async ensureAudioContext(): Promise<AudioContext | null> {
    if (!this.audioContext) {
      try {
        this.audioContext = new AudioContext()
        this.logger.info('PlaybackAudioContext created')
      } catch (error) {
        this.logger.warn('Failed to create AudioContext, audio playback will be disabled', error)
        return null
      }
    }
    if (this.audioContext.state === 'suspended') {
      this.logger.info('AudioContext is suspended, resuming...')
      try {
        await this.audioContext.resume()
        this.logger.info(`AudioContext resumed, new state: ${this.audioContext.state}`)
      } catch (error) {
        this.logger.warn('AudioContext resume failed, audio playback may not work', error)
      }
    }
    return this.audioContext
  }

  async startBGM(): Promise<void> {
    const bgmConfig = this.ttsManager.getBGMConfig()
    if (!bgmConfig.enabled) {
      this.logger.info('BGM disabled in config')
      return
    }

    this.bgmVolume = bgmConfig.volume ?? 0.2

    try {
      let bgmPath = bgmConfig.path
      if (bgmPath.startsWith('resources/builtin/')) {
        const relativePath = bgmPath.replace('resources/builtin/', '')
        bgmPath = builtinResourceUrl(relativePath)
      }

      this.logger.info(`Loading BGM for playback: ${bgmPath}`)
      const response = await fetch(bgmPath)
      if (!response.ok) {
        this.logger.error(`Failed to fetch BGM: HTTP ${response.status}`)
        return
      }

      const arrayBuffer = await response.arrayBuffer()
      const ctx = await this.ensureAudioContext()
      if (!ctx) {
        this.logger.warn('AudioContext not available, skipping BGM decode')
        return
      }
      this.bgmBuffer = await ctx.decodeAudioData(arrayBuffer)
      this.logger.info(`BGM decoded: duration=${this.bgmBuffer.duration.toFixed(2)}s`)

      this.playBGMLoop()
    } catch (error) {
      this.logger.error(
        `Failed to start BGM: ${error instanceof Error ? error.message : String(error)}`
      )
    }
  }

  private playBGMLoop(): void {
    if (!this.bgmBuffer || !this.audioContext) return

    this.stopBGM()

    const ctx = this.audioContext
    this.bgmSource = ctx.createBufferSource()
    this.bgmSource.buffer = this.bgmBuffer
    this.bgmSource.loop = true

    this.bgmGainNode = ctx.createGain()
    this.bgmGainNode.gain.value = this.bgmVolume

    this.bgmSource.connect(this.bgmGainNode)
    this.bgmGainNode.connect(ctx.destination)

    this.bgmSource.start(0)
    this.isBGMPlaying = true
    this.logger.info(`BGM started (loop=true, volume=${this.bgmVolume})`)
  }

  stopBGM(): void {
    if (this.bgmSource) {
      try {
        this.bgmSource.stop()
        this.bgmSource.disconnect()
      } catch {
        /* already stopped */
      }
      this.bgmSource = null
    }
    if (this.bgmGainNode) {
      this.bgmGainNode.disconnect()
      this.bgmGainNode = null
    }
    this.isBGMPlaying = false
  }

  setBGMVolume(volume: number): void {
    this.bgmVolume = volume
    if (this.bgmGainNode) {
      this.bgmGainNode.gain.value = volume
    }
  }

  async playTTSAudio(audioBuffer: ArrayBuffer): Promise<void> {
    try {
      if (audioBuffer.byteLength === 0) {
        this.logger.warn('TTS audio buffer is empty, skipping playback')
        return
      }

      const ctx = await this.ensureAudioContext()
      if (!ctx) {
        this.logger.warn('AudioContext not available, skipping TTS playback')
        return
      }

      const decodedBuffer = await ctx.decodeAudioData(audioBuffer.slice(0))
      this.logger.info(
        `TTS audio decoded: ${decodedBuffer.duration.toFixed(3)}s, ${decodedBuffer.numberOfChannels}ch, ${decodedBuffer.sampleRate}Hz`
      )

      const source = ctx.createBufferSource()
      source.buffer = decodedBuffer

      if (this.currentTTSSource) {
        try {
          this.currentTTSSource.stop()
          this.currentTTSSource.disconnect()
        } catch {
          /* already stopped */
        }
        this.currentTTSSource = null
      }

      if (this.ttsGainNode) {
        try {
          this.ttsGainNode.disconnect()
        } catch {
          /* already disconnected */
        }
        this.ttsGainNode = null
      }

      this.currentTTSSource = source
      this.ttsGainNode = ctx.createGain()
      this.ttsGainNode.gain.value = this.ttsVolume

      source.connect(this.ttsGainNode)
      this.ttsGainNode.connect(ctx.destination)

      this.logger.info(`TTS audio playing at volume ${this.ttsVolume}`)

      return new Promise<void>((resolve) => {
        source.onended = () => {
          try {
            source.disconnect()
          } catch {
            /* already disconnected */
          }
          if (this.ttsGainNode) {
            try {
              this.ttsGainNode.disconnect()
            } catch {
              /* already disconnected */
            }
            this.ttsGainNode = null
          }
          if (this.currentTTSSource === source) {
            this.currentTTSSource = null
          }
          resolve()
        }
        source.start(0)
      })
    } catch (error) {
      this.logger.error(
        `Failed to play TTS audio: ${error instanceof Error ? error.message : String(error)}`
      )
    }
  }

  async playTTSSynthesized(text: string, characterName: string): Promise<number> {
    if (!this.ttsManager.isTTSEnabled()) {
      return 0
    }

    try {
      this.ttsManager.initialize()
      const result = await this.ttsManager.translateAndSynthesize(text, characterName)

      if (result.success && result.duration > 0) {
        const tracks = this.ttsManager.getAudioTracks()
        if (tracks.length > 0) {
          const lastTrack = tracks[tracks.length - 1]
          await this.playTTSAudio(lastTrack.audioBuffer)
          this.ttsManager.clearAudioTracks()
        }
        return result.duration
      }

      this.logger.warn(`TTS synthesis failed for "${characterName}"`)
      return 0
    } catch (error) {
      this.logger.error(
        `TTS playback error for "${characterName}": ${error instanceof Error ? error.message : String(error)}`
      )
      return 0
    }
  }

  isBGMPlayingState(): boolean {
    return this.isBGMPlaying
  }

  dispose(): void {
    this.stopBGM()
    if (this.currentTTSSource) {
      try {
        this.currentTTSSource.stop()
        this.currentTTSSource.disconnect()
      } catch {
        /* already stopped */
      }
      this.currentTTSSource = null
    }
    if (this.ttsGainNode) {
      try {
        this.ttsGainNode.disconnect()
      } catch {
        /* already disconnected */
      }
      this.ttsGainNode = null
    }
    if (this.audioContext) {
      this.audioContext.close()
      this.audioContext = null
    }
    this.bgmBuffer = null
    this.logger.info('PlaybackAudioManager disposed')
  }
}
