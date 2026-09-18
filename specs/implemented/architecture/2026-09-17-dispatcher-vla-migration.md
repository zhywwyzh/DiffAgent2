# VLA 技能迁移的交付决策

Status: implemented

日期：2026-09-17

现行行为归 `l3-skill-contract.spec.md`（§10 VLA 导航技能语义）、
`l3-tool-plane.spec.md`（§1 七工具生产集合）与 `l3-execution-seam.spec.md`。
本记录延续 station 下发 grounded detection、板上零 VLM 的架构方向，记录
本轮实现选择，不替代现行契约。方案全文见
[dispatcher VLA 技能迁移方案](../../../doc/l3-dispatcher-planner/iteration/design-dispatcher-vla-migration.md)。

技能单名 `navigation.vla_nav` 落地，不恢复 `vla` 旧名与任务编号。grounded
消费保持 bbox_1000→像素换算与 fail-closed 三态
（invalid_grounded_bbox / target_not_visible / odom_stamp_unavailable）唯一
fail 终态，无静默回落。远推进（far_push 5 m 沿机头）、0.3 m 接近判定、
高度 clamp 0~1.8 与旧链一致；`depth_match_ok` 语义为候选可信度，方向腿
（side/above/front）同样携带。

`geometry.py` 留在 `tools/vla/` 并头注「vla 专用几何逻辑」，不抽跨域共享
服务；几何原语经 `VlaSkillHost` 组合注入 perception 实例，core 不增领域
几何方法。REPLAN 判据为技能自有 replan 状态，`on_action_result` 四裁决
（REPLAN/ADVANCE/IDLE/NEW_ACTION）不读宿主 `ActionGate.pending_action`；
重新武装后旧代次结果被完成门拒绝（台账 R05 接入顺序落地）。动作完成由
`wait_action_tick` 逐主循环节拍驱动 `poll_result`（与 FlightMotion 同构；
评审发现的空钩断链已修复并以引擎节拍仿真端到端锁定）。

`~vla/*` 参数为 VLA 几何/阈值唯一权威（11 项默认值与旧库逐项一致），
perception 同名属性属 perception 自有。`publish_mode_burst` 以受控空实现
接入（新 EGO 直连栈无 trigger 通道，装配留痕
`vla_planner_mode_channel_absent`，不静默吞错）。`mission_type=NAVIGATION`
由装配侧置位、disposer 恢复；`if_safe_mode` 为旧库孤儿留壳，不迁。

删除项：first 首帧系列（不迁）；`thinking_debug_dir`/`last_thinking_debug_dir`
双侧孤儿字段（台账 R07 关门）；记录消费 `host.recording._record_process_event`
待记录服务（R01/R06）后接入，R05 继续挂账。已知差异：执行启动异常
（odometry 校验失败）沿 plan_tick 上抛走 run_inference 自愈，fail 相位
`error.code=internal_error` 而非语义化原因，属既有机制，登记待后续收敛。

发现面为七工具（六 basic_flight + navigation.vla_nav），revision 与
`l3-tool-plane.spec.md` 记录一致；未注册名仍 `tool_not_registered`，飞行
独占与同源抢占对 VLA 同样适用。全量 206 项测试通过（环境缺 zenoh 的四个
收集失败为既有基线，按 ignore 清单排除）；端到端覆盖引擎节拍驱动的
REPLAN 循环至队列耗尽 done。测试边界止于合成 Frame/OdometryBuffer 与
批次仿真，真机/仿真整链验收待具备 station 下发条件后补充。
