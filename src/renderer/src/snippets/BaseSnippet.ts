import { Snippet } from './Snippet'
import { App } from '../app/App'
import { SnippetData } from '../../../common/types/Story'
import AnimationManager from '../managers/AnimationManager'
import getSubLogger from '../utils/Logger'
import { ILogObj, Logger } from 'tslog'

export default abstract class BaseSnippet implements Snippet {
  protected readonly app: App
  protected readonly logger: Logger<ILogObj>
  protected data!: SnippetData

  constructor(app: App, data: SnippetData) {
    this.app = app
    this.data = data
    this.logger = getSubLogger(this.constructor.name)
  }

  async runSnippet(): Promise<void> {
    await this.runDelay()
    await this.handleSnippet()
  }

  async runDelay(): Promise<void> {
    await AnimationManager.delay(this.data.delay * 1000)
  }

  protected abstract handleSnippet(): Promise<void>
}
