import PositionRel from '../types/PositionRel'
import StageUtils from '../utils/StageUtils'
import BaseSnippet from './BaseSnippet'

// noinspection DuplicatedCode
export default class LayoutAppearSnippet extends BaseSnippet {
  protected async handleSnippet(): Promise<void> {
    if (this.data.type !== 'LayoutAppear') return

    const model = this.app.getModelById(this.data.data.modelId)

    // 在添加模型到舞台前，先获取内部模型的引用，准备阻止idle
    if (model.internalModel) {
      // 在添加前先停止所有动作！
      model.internalModel?.parallelMotionManager[0]?.stopAllMotions()
      model.internalModel?.parallelMotionManager[1]?.stopAllMotions()
    }

    this.app.layerModel.addModelToLayer(model)

    // 确保模型内部已完全初始化
    if (!model.internalModel) {
      this.logger.warn('Model internalModel not ready, waiting...')
      await new Promise((resolve) => setTimeout(resolve, 50))
    }

    // 再次停止所有动作（再次确保idle被阻止）
    model.internalModel?.parallelMotionManager[0]?.stopAllMotions()
    model.internalModel?.parallelMotionManager[1]?.stopAllMotions()

    // 立即应用初始motion和facial（如果有），在show之前就设置好姿态
    if (this.data.data.motion || this.data.data.facial) {
      await model.applyAndWait(
        this.data.data.motion,
        this.data.data.facial,
        this.data.data.facialFirst
      )

      // 强制再播放一次最后一帧，确保姿态完全正确
      await model.playMotionLastFrame(this.data.data.motion, this.data.data.facial)
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

    const show_task = model.show(200, this.data.data.hologram)

    if (from.x !== to.x || from.y !== to.y) {
      model.setPositionRel(this.app.stage_size, to)
    }

    const is_moved = from.x !== to.x || from.y !== to.y

    // 开始平移时立即阻止idle，确保平移过程中也是正确姿态
    if (is_moved) {
      model.internalModel?.parallelMotionManager[0]?.stopAllMotions()
      model.internalModel?.parallelMotionManager[1]?.stopAllMotions()
    }

    const move_task = !is_moved
      ? null
      : model.move(
          this.app.stage_size,
          from,
          to,
          StageUtils.move_speed_to_num(this.data.data.moveSpeed)
        )

    // 等待show和move完成
    await show_task
    if (move_task) {
      await move_task
    }
  }
}
