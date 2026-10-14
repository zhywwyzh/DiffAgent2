# 飞行与 VLA 直连任务结果收敛决策

Status: implemented
Date: 2026-10-09
Record-Format: historical
Supersedes: specs/implemented/architecture/2026-09-20-vla-waypoint-executor.md
Superseded-by: specs/implemented/architecture/2026-10-09-planner-native-action.md

现行职责归 `l3-execution-seam` §8、`l3-skill-contract` §10 和
`flight-actions` §8；过程方案见
[任务结果收敛方案](../../../doc/l3-dispatcher-planner/iteration/design-flight-vla-result-convergence.md)。

DiffAgent2 旧版的 mission reach 流程在 planner 批次结束后还会确认原目标停稳，
有终末偏航时再执行低速原地转向。DiffAgent2 新版直连 planner 时必须承接这些
结果语义，否则会把批次结束误报为任务完成。本轮把通用停稳机制放入各家族
航点执行器，技能继续拥有多腿顺序与任务级完成裁决，不恢复中间任务系统。

VLA 执行失败先终止调用；位置、终末偏航和可选贴地腿按序执行，最后一腿成功
才推进队列。删除缓存感知帧的近点成功路径，headless 同样依赖新鲜 odometry。
贴地不是飞控降落，地面未配置就失败；高度界统一由 FlightConfig 持有，旧 VLA
重复高度键和近点阈值在启动时明确拒绝。共享高度默认沿用飞行配置，VLA 旧
1.8 m 上界不再单独生效，需要相同限制时设置 `~flight/max_height`。

旋转技能在已有分段目标上增加实际有符号累计角核对。完成门使用批次关联加
新鲜动态观测，保留下发目标而不是采用 planner 修正点；同一快照不累计停稳
时间。新增配置按物理量单位命名，既有全量参数改名不并入本轮。

状态速度与角速度沿用现有 planner 的 odometry 数值约定；执行器从递增源时戳
的速度差分求加速度。实际观测或参数噪声使停稳门无法满足时，应失败而不是填零。

本次只完成方案、契约和代码交付。按使用者统一约束，未读取测试文件、未运行
测试、语法验收、构建或仿真；不把历史测试结果作为本次的运行等价证据。
