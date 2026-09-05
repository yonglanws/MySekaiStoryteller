import { Muxer, ArrayBufferTarget } from 'mp4-muxer'

export interface EncodedFrame {
  data: Uint8Array
  timestamp: number
  isKeyFrame: boolean
}

export interface MuxerConfig {
  width: number
  height: number
  fps: number
  codec?: 'avc' | 'hevc' | 'vp9'
  enableHardwareAcceleration?: boolean
}

export class StreamMuxer {
  private muxer: Muxer<ArrayBufferTarget> | null = null
  private videoEncoder: VideoEncoder | null = null
  private encodedFrames: EncodedFrame[] = []
  private frameCount: number = 0
  private config: MuxerConfig
  private encodingQueue: Array<{
    canvas: HTMLCanvasElement
    frameIndex: number
    resolve: () => void
    reject: (error: Error) => void
  }> = []
  private isProcessingQueue: boolean = false
  private maxQueueSize: number = 16
  private hardwareAccelerationSupported: boolean = false

  constructor(config: MuxerConfig) {
    this.config = config
  }

  async initialize(): Promise<void> {
    try {
      this.hardwareAccelerationSupported = await this.detectHardwareAccelerationSupport()
    } catch {
      this.hardwareAccelerationSupported = false
    }

    const useHardware =
      this.config.enableHardwareAcceleration !== false && this.hardwareAccelerationSupported

    try {
      this.muxer = new Muxer({
        target: new ArrayBufferTarget(),
        video: {
          codec: 'avc',
          width: this.config.width,
          height: this.config.height
        },
        fastStart: 'in-memory',
        firstTimestampBehavior: 'offset'
      })
    } catch (error) {
      throw new Error(
        `Failed to initialize MP4 muxer: ${error instanceof Error ? error.message : String(error)}`
      )
    }

    try {
      this.videoEncoder = new VideoEncoder({
        output: (chunk, metadata) => {
          const data = new Uint8Array(chunk.byteLength)
          chunk.copyTo(data)
          this.encodedFrames.push({
            data,
            timestamp: chunk.timestamp,
            isKeyFrame: metadata?.decoderConfig !== undefined
          })
        },
        error: (error) => {
          this.encodedFrames = []
          throw new Error(`VideoEncoder error: ${error.message}`)
        }
      })

      const codecConfig = this.getOptimizedCodecConfig(useHardware)
      this.videoEncoder.configure(codecConfig)
    } catch (error) {
      this.muxer = null
      throw new Error(
        `Failed to initialize video encoder: ${error instanceof Error ? error.message : String(error)}`
      )
    }
  }

  private async detectHardwareAccelerationSupport(): Promise<boolean> {
    const hwCodecs = ['avc1.4D4028', 'avc1.42E01E', ' hev1.1.6.L93.B0']

    for (const codec of hwCodecs) {
      try {
        const support = await VideoEncoder.isConfigSupported({
          codec: codec.trim(),
          width: this.config.width,
          height: this.config.height,
          bitrate: 8_000_000,
          framerate: this.config.fps,
          hardwareAcceleration: 'prefer-hardware'
        })
        if (support.supported) {
          return true
        }
      } catch {
        continue
      }
    }
    return false
  }

  private getOptimizedCodecConfig(useHardware: boolean): VideoEncoderConfig {
    const baseConfig: VideoEncoderConfig = {
      codec: useHardware ? 'avc1.4D4028' : 'avc1.42001F',
      width: this.config.width,
      height: this.config.height,
      bitrate: this.calculateOptimalBitrate(),
      framerate: this.config.fps,
      latencyMode: 'quality'
    }

    if (useHardware) {
      baseConfig.hardwareAcceleration = 'prefer-hardware'
    }

    return baseConfig
  }

  private calculateOptimalBitrate(): number {
    const pixelCount = this.config.width * this.config.height
    const fpsFactor = this.config.fps / 30

    if (pixelCount > 1920 * 1080) {
      return Math.round(12_000_000 * fpsFactor)
    } else if (pixelCount > 1280 * 720) {
      return Math.round(8_000_000 * fpsFactor)
    } else {
      return Math.round(5_000_000 * fpsFactor)
    }
  }

  async encodeFrame(canvas: HTMLCanvasElement, frameIndex: number): Promise<void> {
    if (this.encodingQueue.length >= this.maxQueueSize) {
      await new Promise<void>((resolve, reject) => {
        this.encodingQueue.push({ canvas, frameIndex, resolve, reject })
        this.processQueue()
      })
    }

    return new Promise<void>((resolve, reject) => {
      this.encodingQueue.push({ canvas, frameIndex, resolve, reject })
      this.processQueue()
    })
  }

  private async processQueue(): Promise<void> {
    if (this.isProcessingQueue || this.encodingQueue.length === 0) {
      return
    }

    this.isProcessingQueue = true

    try {
      while (this.encodingQueue.length > 0) {
        const { canvas, frameIndex, resolve, reject } = this.encodingQueue.shift()!

        try {
          const frame = new VideoFrame(canvas, {
            timestamp: (frameIndex * 1_000_000) / this.config.fps
          })

          try {
            this.videoEncoder!.encode(frame, { keyFrame: frameIndex % 30 === 0 })
          } finally {
            frame.close()
          }
          this.frameCount++
          resolve()
        } catch (error) {
          reject(error instanceof Error ? error : new Error(String(error)))
        }
      }
    } finally {
      this.isProcessingQueue = false
    }
  }

  async finalize(): Promise<Uint8Array> {
    try {
      await this.videoEncoder!.flush()
    } catch (error) {
      throw new Error(
        `Failed to flush video encoder: ${error instanceof Error ? error.message : String(error)}`
      )
    } finally {
      this.videoEncoder?.close()
      this.videoEncoder = null
    }

    try {
      for (const encodedFrame of this.encodedFrames) {
        this.muxer!.addVideoChunkRaw(
          encodedFrame.data,
          encodedFrame.isKeyFrame ? 'key' : 'delta',
          encodedFrame.timestamp,
          1_000_000 / this.config.fps,
          undefined,
          0
        )
      }

      this.muxer!.finalize()
      const target = this.muxer!.target as ArrayBufferTarget
      return new Uint8Array(target.buffer!)
    } catch (error) {
      throw new Error(
        `Failed to finalize MP4 muxer: ${error instanceof Error ? error.message : String(error)}`
      )
    } finally {
      this.encodedFrames = []
    }
  }

  getFrameCount(): number {
    return this.frameCount
  }

  dispose(): void {
    this.encodingQueue.forEach(({ reject }) => {
      reject(new Error('StreamMuxer disposed'))
    })
    this.encodingQueue.length = 0

    this.videoEncoder?.close()
    this.videoEncoder = null
    this.muxer = null
    this.encodedFrames = []
  }
}
