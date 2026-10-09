# 飞行与 VLA 任务结果收敛方案

> 摘要：在 dispatcher 直连 planner 的架构中补齐失败传播、目标停稳、终末偏航、贴地腿和累计旋转判定。依据现行 l3 契约及 DiffAgent2 旧版生产调用链，不恢复中间任务系统。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-10-09 |
| 目标路径 | `l3-dispatcher-planner/ros_packages/dispatcher/` |
| 状态 | 验收未通过（领域新增用例通过；既有回归与集成阻塞待收敛） |
| 关联文档 | `specs/implemented/inner/l3-execution-seam.spec.md`、`l3-skill-contract.spec.md`、`flight-actions.spec.md`；`doc/l3-dispatcher-planner/rest/dispatcher-deferred-dependencies.md` |

## 1. 背景与动机

DiffAgent2 新版删除中间执行层后，批次结束被直接视为动作成功。DiffAgent2 旧版的 `mission_core_reach.cpp` 在批次结束后另行检查原目标停稳，再执行终末偏航。需要把仍有消费者的结果语义迁入技能及家族执行器，保持直连架构。

## 2. 现状事实（问题清单）

以下行号为实施前定位，路径相对新版 dispatcher 包，旧版项另行标明。

- `tools/vla/vla_skill.py:177` — 收尾不检查执行失败；`:195` 提前推进队列后才发贴地腿；`:116` 用缓存帧直接成功。
- `tools/flight/flight_waypoint.py:69`、`tools/vla/vla_waypoint.py:69` — all_consumed 直接成功。
- `tools/vla/ports.py:36`、`execution/ports.py:11` — 高度配置重复且下界不同。
- `tools/flight/rotate_skill.py:18` — 只有目标分段，没有实际偏航累计。
- DiffAgent2 旧版 `drone_projects/l3-dispatcher-planner/ros_packages/mission_executive/src/handlers/mission_core_reach.cpp:96` — 原目标位置、速度、加速度、偏航角速度持续停稳；`:130` — 终末偏航腿。

## 3. 目标与约束

- 失败立即结束；批次成功加真实目标停稳才构成动作成功；同一次调用所有腿完成后只报告一个终态。
- 范围为机上执行结果差异；站端几何、返航产品范围、工具名和 planner 算法保持现行契约。
- 禁止转接器、旧接口兼容壳、任务编号和第二套任务队列。
- 初次实现按统一声明跳过验收；用户现已明确授权，开展领域及集成验收，代码完成与验收结果分别记录。
- core 依赖整理、全量既有参数改名与通用 schema 原因码归一另行处理，不扩大本轮行为修复范围。

## 4. 方案决策

目标目录沿用：

```text
dispatcher/
  execution/{ports,skill_host,composition}.py
  ros_adapter/planner_execution_ros.py
  tools/flight/{flight_waypoint,rotate_skill,motion}.py
  tools/vla/{ports,vla_skill,vla_waypoint}.py
```

| 类型 | 规范 | 示例 |
|------|------|------|
| 家族执行器 | 家族前缀 | `vla_waypoint.py` |
| 新配置 | 明确物理量及单位 | `settle_hold_s`、`settle_position_m` |
| 技能子状态 | 私有语义名 | `_terminal_yaw` |

- `FlightState` 增加速度向量、偏航角速度；加速度由家族执行器按连续 odometry 时戳差分，ROS 层只转换快照，不作完成判定。缺少动态信息不得伪造停稳。
- 执行器保留实际下发目标、批次完成标志和连续停稳窗口；使用新鲜、时戳递增的观测，重复快照不累计停稳时间；超时含批次后的停稳等待。
- 默认停稳阈值沿用旧版：位置 0.30 m、速度 0.15 m/s、加速度 0.30 m/s²、偏航角速度 0.20 rad/s、持续 0.20 s、终末偏航 10°。飞行与 VLA 共用 `FlightConfig` 唯一配置。
- 启动资源按获取逆序登记到 ExitStack；旧参数拒绝或 VLA 装配失败也释放已创建的飞行资源。
- VLA 删除近点直接成功路径；近点同样经新鲜 odometry、planner 反馈及停稳门收尾。删除失去消费者的近点阈值。
- VLA 显式 yaw 拆为位置腿与终末旋转腿；贴地腿接在其后，失败不推进。贴地腿仅为目标下发，不新增飞控降落指令。
- 普通高度界由 `FlightConfig` 统一拥有。贴地意图显式标记 `ground_approach`，须配置 ground_z，目标为地面高度加 `final_approach_height_m`（默认 0.1 m）；仍受最大高度约束，未配置地面即失败。
- 旋转技能连续解缠实际 yaw，并在每段收尾核对累计角；缺观测、倒退时戳或累计角不符明确失败。
- 旧版模式脉冲现存接线不在本轮扩展；执行失败原因继续经现有工具面终态映射。

## 5. 迁移映射表

| 旧路径/命名 | 新路径/命名 | 动作 | 备注 |
|-------------|-------------|------|------|
| 旧版 reachExec 停稳门 | 两家族 waypoint 执行器 | rewrite | 参数与状态端口共享，执行实现按现行目录契约各自拥有 |
| 旧版 post-yaw | VlaSkill 内部腿 | rewrite | 无额外外部调用 |
| 缓存帧近点成功 | 新鲜状态与统一完成门 | delete | 不保留短路 |
| VLA 重复高度配置 | FlightConfig | merge | 旧 vla 高度参数不兼容，装配明确拒绝 |
| 分段目标旋转 | 实际累计角加分段目标 | rewrite | 保持符号及跨圈语义 |

## 6. 删除清单

| 删除项 | 理由 |
|--------|------|
| VLA 无条件成功收尾与贴地前 advance | 终态错误 |
| 近点成功分支和 search_success_distance_thresh | 绕过新鲜度与完成门 |
| VlaHostConfig.min_height/max_height | 重复高度权威 |
| all_consumed 直接 ActionResult(True) | 批次结束不等于原目标停稳 |

## 7. 实施步骤（P0/P1/... 分期）

### P0 — 契约与方案

- 范围：登记端口、停稳配置、VLA 多腿与贴地例外。
- 不变量：维持直连架构和六态 core。
- 验收：按用户统一声明跳过。
- 回退：契约与对应实现作为一个整体撤回。

### P1 — 执行结果

- 范围：状态快照、家族执行器、停稳和累计旋转。
- 不变量：保持批次不作为成功反馈；失败保留停止待处理守卫。
- 验收：待明确许可后覆盖提前反馈、原目标偏差、动态未稳、重复快照和超时。
- 回退：连同新端口回退本期改动。

### P2 — VLA 收尾

- 范围：失败传播、位置/偏航/贴地腿、统一高度和新鲜状态。
- 不变量：只有最终腿成功才推进队列；任一失败均不继续发腿。
- 验收：待许可后覆盖多腿成功/失败/取消和 headless。
- 回退：代码与技能契约同批回退。

### P3 — 交付记录

- 范围：同步 rest 索引、R03/R05 与架构决策。
- 不变量：代码交付不得表述为实机或仿真等价已验收。
- 验收：本轮不运行。
- 回退：与实现记录同步撤回。

## 8. 验收标准

> **统一声明**：除非使用者明确许可，否则跳过验收测试工作（`AGENTS.md` 硬性约束 §9）。初次实现未执行；用户后续明确授权，执行结果见下文。

- 失败、超时、取消不产生成功或后继腿。
- 批次结束后位置/速度/加速度/偏航角速度/终末 yaw 任一未满足不成功。
- 旧批次、旧时戳、重复快照不能推进新动作或停稳计时。
- VLA 近点、终末旋转、贴地腿均保留唯一终态。
- 多圈与跨 ±π 旋转的实际累计角满足请求；未知地面贴地失败。
- 后续经许可补领域及至 cmd 的受控集成验收；现有历史通过记录不覆盖本轮。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| odometry 动态信息缺失或差分噪声 | 无法确认停稳 | 明确等待/失败，不填零；阈值配置同源 |
| 默认高度上界统一 | VLA 限幅范围由 flight 配置决定 | 明确登记配置变化，拒绝旧重复配置 |
| 分腿延长执行 | 终态比旧版提前成功路径更晚 | 每腿有明确超时，整体由有限腿数约束 |
| 禁止验收 | 无运行等价证据 | 完成记录明确标注未验收 |

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|------|------|------|
| `specs/implemented/inner/l3-execution-seam.spec.md` | 修改 | 状态、完成门与共享配置 |
| `specs/implemented/inner/l3-skill-contract.spec.md` | 修改 | VLA 端口及多腿终态 |
| `specs/implemented/inner/flight-actions.spec.md` | 修改 | 旋转实测累计与停稳 |
| `execution/ports.py`、`ros_adapter/planner_execution_ros.py` | 修改 | 意图、状态及配置 |
| `tools/*/*_waypoint.py` | 修改 | 原目标停稳门 |
| `tools/flight/rotate_skill.py` | 修改 | 实际偏航累计 |
| `tools/vla/{vla_skill,ports}.py` | 修改 | 多腿、单终态和配置 |
| `execution/{skill_host,composition}.py`、`dispatcher_node.py` | 修改 | 新端口及配置接线 |
| rest 索引、台账和架构决策 | 修改/新增 | 交付与剩余触发条件 |

实施记录（2026-10-09）：P0–P3 的契约、代码与台账已落地。未运行测试、
语法验收、构建、仿真或门禁；§8 判据仍未验收。未提交或推送。
新增状态字段会要求未来测试夹具携带真实动态观测；VLA 构造参数移除
近点阈值，后续经许可同步测试。决策已归档至
`specs/implemented/architecture/2026-10-09-flight-vla-result-convergence.md`。

验收执行补充（2026-10-09）：用户明确要求开始验收。先运行现有全量测试，
再新增独立的连续 odometry 用例覆盖两家族的完成门、失败和 VLA 多腿终态；
保留旧测试失败证据，不通过删除断言或恢复旧接口获得通过。验收结果记录在本方案。

### 本次验收结果（2026-10-09）

- 环境：隔离 Python 环境安装 `tests/requirements.txt`；初次缺少 zenoh，安装时的代理依赖问题已绕过。未修改生产运行环境。
- 全量命令：`python -m pytest l3-dispatcher-planner/tests -q --tb=no`。
- 最终结果：**190 通过、26 失败、4 个错误，整体验收未通过**。
- 新增 `tests/basic-flight/test_result_convergence.py`，26 项全部通过：两个家族的批次提前结束、重复快照、位置/速度/加速度/偏航角速度/偏航角约束、动态观测缺失、停稳超时与迟到反馈；VLA 位置→终末偏航→贴地顺序和每腿失败；真实 dispatcher 循环的平移、正反向 450° 旋转、VLA 两腿唯一成功终态。
- `git diff --check` 通过。本次没有修改生产代码，没有提交或推送。

| 未通过项 | 证据与后续处理 |
|----------|----------------|
| 25 项既有领域/宿主/装配测试 | 仍假定 all_consumed 直接成功、缓存近点短路、旧私有状态、六维内部航点、已移除参数或 latest_frame 端口。新用例已提供部分替代行为证据，但原测试尚未全部迁移，不能将失败视为通过；需要逐项同步连续 odometry 夹具及多腿预期，同时保留取消、抢占、代次守卫覆盖。 |
| 1 项 core 依赖边界测试 | `core/skill_router.py` 与 `core/tool_workflow.py` 依赖 `tool_plane.model`；HEAD 中同样存在，属于方案已列出的既有越界，仍不符合边界门禁，需单独收敛方案。 |
| 4 项站端/ROS 集成错误 | 共同前置夹具读取 `l4-agent/src/copaw/station_sidecar/methods.py` 时文件不存在；真实站端 RPC 与 ROS/planner 至 cmd 验收尚未执行，需恢复匹配的站端测试依赖后复跑。 |

本次新增用例使用受控 odometry 和 planner 反馈，验证 dispatcher 的判定与流程；
不构成真实 planner 轨迹、实机动态噪声或 DiffAgent2 旧版端到端结果等价证明。
正反向旋转用例以连续跨 ±π 观测驱动实际循环；贴地三腿用例检验技能裁决，
尚未覆盖真实地面接近运动。先前“代码交付”不能解释为“已修改好且验收通过”。
