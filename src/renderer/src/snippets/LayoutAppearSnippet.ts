import PositionRel from '../types/PositionRel'
import StageUtils from '../utils/StageUtils'
import BaseSnippet from './BaseSnippet'

// noinspection DuplicatedCode
export default class LayoutAppearSnippet extends BaseSnippet {
  protected async handleSnippet(): Promise<void> {
    if (this.data.type !== 'LayoutAppear') return

    const model = this.app.getModelById(this.data.data.modelId)

    // 阻止 idle 动作干扰入场表演
    model.internalModel?.parallelMotionManager[0]?.stopAllMotions()
    model.internalModel?.parallelMotionManager[1]?.stopAllMotions()

    this.app.layerModel.addModelToLayer(model)

    // 确保模型内部已完全初始化
    if (!model.internalModel) {
      this.logger.warn('Model internalModel not ready, waiting...')
      await new Promise((resolve) => setTimeout(resolve, 50))
    }

    const from: PositionRel = StageUtils.side_to_position(
      this.data.data.from.side,
      this.app.layerModel.layoutMode,
      this.data.data.from.offset
    )
    const to: PositionRel = StageUtils.side_to_position(
      this.data.data.to.side,
      this.app.layerModel.layoutMode,
      this.data.data.to.offset
    )

    const is_moved = from.x !== to.x || from.y !== to.y
    model.setPositionRel(this.app.stage_size, is_moved ? from : to)

    // 淡入、滑入、入场动作三者并发：动作在滑动过程中持续播放，禁止站桩滑动
    const show_task = model.show(200, this.data.data.hologram)
    const move_task = is_moved
      ? model.move(
          this.app.stage_size,
          from,
          to,
          StageUtils.move_speed_to_num(this.data.data.moveSpeed)
        )
      : null
    const motion_task =
      this.data.data.motion || this.data.data.facial
        ? model.applyAndWait(
            this.data.data.motion,
            this.data.data.facial,
            this.data.data.facialFirst
          )
        : null

    await show_task
    if (move_task) {
      await move_task
    }
    if (motion_task) {
      await motion_task
    }
  }
}
