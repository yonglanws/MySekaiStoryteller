import PositionRel from '../types/PositionRel'
import StageUtils from '../utils/StageUtils'
import BaseSnippet from './BaseSnippet'

// noinspection DuplicatedCode
export default class LayoutClearSnippet extends BaseSnippet {
  protected async handleSnippet(): Promise<void> {
    if (this.data.type !== 'LayoutClear') return

    const model = this.app.getModelById(this.data.data.modelId)

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
    const move_duration_ms = is_moved ? StageUtils.move_speed_to_num(this.data.data.moveSpeed) : 0

    // 退场动作先加载并启动（滑出全程动作在播），淡出与滑出等长：角色边演边走边隐
    const exit_motion = this.data.data.motion
    const exit_facial = this.data.data.facial
    if (exit_motion || exit_facial) {
      await model.startMotions(exit_motion || undefined, exit_facial || undefined, true)
    }

    const hide_duration_ms = is_moved ? Math.max(move_duration_ms, 400) : 300
    const hide_task = model.hide(hide_duration_ms)

    if (!is_moved) {
      model.setPositionRel(this.app.stage_size, to)
    }

    const move_task = is_moved ? model.move(this.app.stage_size, from, to, move_duration_ms) : null

    await hide_task
    if (move_task) await move_task

    // 动画全部结束后再移出渲染层；提前移除会导致淡出/滑出不可见（硬切消失）
    this.app.layerModel.removeModel(model)
  }
}
