import { ILogObj, Logger } from 'tslog'
import getSubLogger from '../../utils/Logger'

export interface CheckpointData {
  lastSnippetIndex: number
  lastFrameIndex: number
  totalFramesCaptured: number
  timestamp: number
  exportOptions: Record<string, unknown>
}

export class CheckpointManager {
  private readonly logger: Logger<ILogObj>
  private checkpoint: CheckpointData | null = null
  private readonly checkpointKey = 'video-export-checkpoint'

  constructor() {
    this.logger = getSubLogger('CheckpointManager')
  }

  saveCheckpoint(data: CheckpointData): void {
    try {
      this.checkpoint = data
      localStorage.setItem(this.checkpointKey, JSON.stringify(data))
    } catch (error) {
      this.logger.warn('Failed to save checkpoint:', error)
    }
  }

  loadCheckpoint(): CheckpointData | null {
    try {
      const stored = localStorage.getItem(this.checkpointKey)
      if (stored) {
        this.checkpoint = JSON.parse(stored)
        return this.checkpoint
      }
    } catch (error) {
      this.logger.warn('Failed to load checkpoint:', error)
    }
    return null
  }

  clearCheckpoint(): void {
    try {
      this.checkpoint = null
      localStorage.removeItem(this.checkpointKey)
    } catch (error) {
      this.logger.warn('Failed to clear checkpoint:', error)
    }
  }

  hasCheckpoint(): boolean {
    return this.checkpoint !== null
  }

  getCurrentCheckpoint(): Readonly<CheckpointData> | null {
    return this.checkpoint
  }

  canResume(targetTotalSnippets: number): boolean {
    if (!this.checkpoint) return false

    const maxAge = 24 * 60 * 60 * 1000
    const isFresh = Date.now() - this.checkpoint.timestamp < maxAge

    return isFresh && this.checkpoint.lastSnippetIndex < targetTotalSnippets
  }
}
