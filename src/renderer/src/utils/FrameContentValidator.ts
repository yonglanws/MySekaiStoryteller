import { ILogObj, Logger } from 'tslog'
import getSubLogger from '../utils/Logger'

export interface FrameValidationResult {
  isValid: boolean
  brightness: number
  isBlackScreen: boolean
  isBlankScreen: boolean
  error?: string
}

export class FrameContentValidator {
  private logger: Logger<ILogObj> = getSubLogger('FrameContentValidator')

  private readonly BLACK_THRESHOLD = 2
  private readonly BLANK_THRESHOLD = 5
  private readonly SAMPLE_INTERVAL = 8
  private consecutiveBlackFrames = 0
  private readonly MAX_CONSECUTIVE_BLACK = 10

  public validateFrame(canvas: HTMLCanvasElement, frameIndex: number): FrameValidationResult {
    try {
      const result = this.analyzeFrame(canvas, frameIndex)

      if (result.isBlackScreen) {
        this.consecutiveBlackFrames++

        if (this.consecutiveBlackFrames >= this.MAX_CONSECUTIVE_BLACK) {
          result.isValid = false
          result.error = `Detected ${this.consecutiveBlackFrames} consecutive black frames - rendering failure`
          this.logger.error(`Frame validation FAILED at frame ${frameIndex}: ${result.error}`)
        } else {
          this.logger.warn(
            `Black frame detected at frame ${frameIndex} (${this.consecutiveBlackFrames}/${this.MAX_CONSECUTIVE_BLACK})`
          )
        }
      } else {
        if (this.consecutiveBlackFrames > 0) {
          this.logger.info(
            `Black frame streak ended at frame ${frameIndex} (was ${this.consecutiveBlackFrames} frames)`
          )
        }
        this.consecutiveBlackFrames = 0
        result.isValid = true
      }

      return result
    } catch (e) {
      this.logger.error(`Frame validation error at frame ${frameIndex}:`, e)
      return {
        isValid: false,
        brightness: 0,
        isBlackScreen: true,
        isBlankScreen: true,
        error: `Validation error: ${e instanceof Error ? e.message : String(e)}`
      }
    }
  }

  private analyzeFrame(canvas: HTMLCanvasElement, frameIndex: number): FrameValidationResult {
    const gl =
      canvas.getContext('webgl2', { preserveDrawingBuffer: true }) ||
      canvas.getContext('webgl', { preserveDrawingBuffer: true })

    if (!gl) {
      return {
        isValid: false,
        brightness: 0,
        isBlackScreen: true,
        isBlankScreen: true,
        error: 'WebGL context not available'
      }
    }

    if (gl.isContextLost()) {
      return {
        isValid: false,
        brightness: 0,
        isBlackScreen: true,
        isBlankScreen: true,
        error: 'WebGL context lost'
      }
    }

    const width = canvas.width
    const height = canvas.height

    if (width === 0 || height === 0) {
      return {
        isValid: false,
        brightness: 0,
        isBlackScreen: true,
        isBlankScreen: true,
        error: 'Canvas has zero dimensions'
      }
    }

    const sampleWidth = Math.min(width, 64)
    const sampleHeight = Math.min(height, 64)
    const pixels = new Uint8Array(sampleWidth * sampleHeight * 4)

    try {
      gl.readPixels(0, 0, sampleWidth, sampleHeight, gl.RGBA, gl.UNSIGNED_BYTE, pixels)
    } catch (e) {
      return {
        isValid: false,
        brightness: 0,
        isBlackScreen: true,
        isBlankScreen: true,
        error: `Failed to read pixels: ${e instanceof Error ? e.message : String(e)}`
      }
    }

    let totalBrightness = 0
    let validPixelCount = 0
    let hasContent = false

    for (let y = 0; y < sampleHeight; y += this.SAMPLE_INTERVAL) {
      for (let x = 0; x < sampleWidth; x += this.SAMPLE_INTERVAL) {
        const idx = (y * sampleWidth + x) * 4
        const r = pixels[idx]
        const g = pixels[idx + 1]
        const b = pixels[idx + 2]
        const a = pixels[idx + 3]

        if (a > 10) {
          const brightness = (r * 0.299 + g * 0.587 + b * 0.114) / 255
          totalBrightness += brightness
          validPixelCount++

          if (brightness > 0.05) {
            hasContent = true
          }
        }
      }
    }

    const averageBrightness = validPixelCount > 0 ? (totalBrightness / validPixelCount) * 100 : 0

    const isBlackScreen = averageBrightness < this.BLACK_THRESHOLD && !hasContent
    const isBlankScreen = averageBrightness < this.BLANK_THRESHOLD

    if (frameIndex % 30 === 0 || isBlackScreen) {
      this.logger.debug(
        `Frame ${frameIndex}: brightness=${averageBrightness.toFixed(2)}%, black=${isBlackScreen}, blank=${isBlankScreen}`
      )
    }

    return {
      isValid: !isBlackScreen,
      brightness: averageBrightness,
      isBlackScreen,
      isBlankScreen
    }
  }

  public reset(): void {
    this.consecutiveBlackFrames = 0
  }

  public getConsecutiveBlackFrames(): number {
    return this.consecutiveBlackFrames
  }

  public hasReachedBlackFrameLimit(): boolean {
    return this.consecutiveBlackFrames >= this.MAX_CONSECUTIVE_BLACK
  }
}

export const frameValidator = new FrameContentValidator()
