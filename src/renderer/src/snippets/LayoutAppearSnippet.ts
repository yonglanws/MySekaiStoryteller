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

    // 淡入、入场动作、滑入并发：动作先加载并启动（await 到"已开始播放"），
    // 随后立即启动滑动——滑入全程动作在播，杜绝站桩滑动。
    const show_task = model.show(200, this.data.data.hologram)

    let motions_started = false
    if (this.data.data.motion || this.data.data.facial) {
      await model.startMotions(
        this.data.data.motion,
        this.data.data.facial,
        this.data.data.facialFirst
      )
      motions_started = true
    }

    const move_task = is_moved
      ? model.move(
          this.app.stage_size,
          from,
          to,
          StageUtils.move_speed_to_num(this.data.data.moveSpeed)
        )
      : null

    await show_task
    if (move_task) {
      await move_task
    }
    if (motions_started) {
      // 入场动作播完再继续剧情：角色到位并完成动作后才开始说话（与原项目一致）
      await model.waitForMotionsFinished()
    }
  }
}
