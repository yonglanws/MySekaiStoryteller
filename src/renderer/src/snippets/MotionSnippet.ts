import BaseSnippet from './BaseSnippet'

export default class MotionSnippet extends BaseSnippet {
  protected async handleSnippet(): Promise<void> {
    if (this.data.type !== 'Motion') return

    const model = this.app.getModelById(this.data.data.modelId)
    this.app.layerModel.addModelToLayer(model)

    model.internalModel?.parallelMotionManager[0]?.stopAllMotions()
    model.internalModel?.parallelMotionManager[1]?.stopAllMotions()

    await new Promise((resolve) => requestAnimationFrame(resolve))

    await model.applyAndWait(
      this.data.data.motion,
      this.data.data.facial,
      this.data.data.facialFirst
    )

    await model.playMotionLastFrame(this.data.data.motion, this.data.data.facial)
  }
}
