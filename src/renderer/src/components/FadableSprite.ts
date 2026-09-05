import { AlphaFilter, Sprite, Texture } from 'pixi.js'
import AnimationManager from '../managers/AnimationManager'

export default class FadableSprite extends Sprite {
  protected constructor(texture: Texture) {
    super(texture)

    const alpha_filter = new AlphaFilter(0)
    alpha_filter.resolution = 2
    this.filters = [alpha_filter]
  }

  public async show(time: number): Promise<void> {
    this.visible = true
    const alphaFilter: AlphaFilter = this.filters![0] as AlphaFilter
    alphaFilter.alpha = 0

    await AnimationManager.linear((progress) => {
      alphaFilter.alpha = progress
    }, time)
  }

  public async hide(time: number): Promise<void> {
    const alphaFilter: AlphaFilter = this.filters![0] as AlphaFilter
    alphaFilter.alpha = 1

    await AnimationManager.linear((progress) => {
      alphaFilter.alpha = 1 - progress
    }, time)

    this.visible = false
  }
}
