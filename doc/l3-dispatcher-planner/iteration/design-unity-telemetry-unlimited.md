# Unity 遥测解除限速方案

> 摘要：按用户要求删除 DiffAgent2 新版 Unity 遥测的通道抽帧、聚合带宽限速与固定轮询等待，改为最新值到达唤醒发送。范围为本仓库的 Unity 装配及独立遥测生产者；依据为用户本轮明确指令和 Git 历史调查，关联资料见 [Unity 启动方案](design-k3s-unity-bringup.md)。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-10-15 |
| 目标路径 | deployment/k3s/unity、deployment/tools/station-host-sim.py、drone_projects/l3-dispatcher-planner/ros_packages/telemetry_bridge |
| 状态 | in-progress；方案先行，检查与运行验收未获许可 |
| 关联文档 | specs/proposed/inner/station-telemetry.spec.md、specs/proposed/inner/unity-k3s-bringup.spec.md |

## 1. 背景与动机

用户要求解除 Unity 仿真的遥测速度上限。DiffAgent2 旧版提交 ca35ef7 为仿真增加独立相机发送线程并设置 15 Hz；L4 提交 3d6bbf3、f4321c1 保留仿真快速转发。DiffAgent2 新版提交 78c8aa9 新建独立 telemetry_bridge 时设置了更低的频率和聚合带宽上限。本轮直接删除新版 Unity 限速，不迁入旧任务栈或另建转接层。

## 2. 现状事实（问题清单）

- [ ] `deployment/k3s/unity/runtime.defaults.env#L35-L39`：RGB 5 Hz、深度及点云 3 Hz、里程计 10 Hz、聚合带宽 8 Mbit/s。
- [ ] `deployment/tools/station-host-sim.py#L114-L125`：限速配置必须为正，相机上限不得超过 15 Hz，无法表达无上限。
- [ ] `deployment/tools/station-host-sim.py#L384-L398`：Player 采样率与遥测相机上限使用同一配置；遥测 JSON 生成 rates 和 mbit。
- [ ] `drone_projects/l3-dispatcher-planner/ros_packages/telemetry_bridge/src/telemetry_bridge/uplink.py#L60-L83`：固定 20 ms 轮询、通道间隔判断和按字节带宽等待共同限制传输。
- [ ] `drone_projects/l3-dispatcher-planner/ros_packages/telemetry_bridge/scripts/telemetry_ros.py#L26-L27`：ROS 装配把含限速字段的 settings 传入 Uplink。

## 3. 目标与约束

- **目标**：Unity 的 camera、depth、cloud、drone_status 在有新值时立即交给编码发送线程，不设置额外 Hz 或 Mbit/s 上限，不用极大常数模拟无限。
- **非目标**：改变传感器本身的采样能力、遥测线上载荷、图像编码质量、点云空间降采样、真机部署、独立 L2/L4 仓库或传输拓扑。
- **硬边界**：每通道只保留最新待发值；ROS 回调不编码、不等待网络；错误日志节流及源时戳检查继续保留；不新增新旧接口转接器，不保留退役限速入口。
- 现有遥测经 ROS 和显式 Zenoh router 传输，不能把本机部署描述为全程共享内存；解除人为限速不表示消除编码、网络及消费者处理耗时。
- 遵循 AGENTS.md §9：不读取测试资料，不执行测试、门禁、验证性验收、构建或部署。本轮基线捕获仅写主机忽略区。

## 4. 方案决策

- **目标目录树**：保持 deployment/k3s/unity 的配置和说明、deployment/tools 的装配入口、telemetry_bridge/scripts 的 ROS 装配、telemetry_bridge/src/telemetry_bridge 的编码与发送模块分工，不增加目录或第二套实现。
- **命名规范**：Python 文件、方法和私有成员沿用 snake_case，类沿用 PascalCase，配置沿用带单位的大写下划线。原生 Player 的采样配置命名为 SIM_UNITY_SENSOR_RATE_HZ；它只生成 Player 的 camera.rate_hz，不参与遥测发送。
- **接口形态**：遥测配置仅保留 cloud_leaf 和 cloud_max_points；通道集合由生产者固定声明。Uplink 删除 settings 参数，ROS 装配同步修改调用。
- **调度**：submit 拒绝未知频道，在条件变量保护下覆盖最新值并通知后台线程；后台逐通道消费最新值、编码、发送。无新值时等待提交、关停通知或每秒健康报告期限；有值时不执行限速 sleep。关停唤醒并等待最多 5 秒，线程未退出时明确报错并保留 Zenoh 资源。
- **Player 采样**：新增 SIM_UNITY_SENSOR_RATE_HZ，默认 30 Hz，接受正有限值、不设置最大值；original/editor 的源采样仍由原场景控制。
- **旧接口 → 删除**：删除 SIM_CAMERA_MAX_HZ、SIM_DEPTH_MAX_HZ、SIM_CLOUD_MAX_HZ、SIM_ODOM_MAX_HZ、SIM_TELEMETRY_MBIT、rates、mbit 和对应验证、间隔及带宽等待。旧主机覆盖键按既有未知键规则明确拒绝，不提供兼容映射。
- **配置与制品**：源码和配置按同一轮更新；下次依原入口重新 prepare 和启动，禁止修改成功摘要冒充已构建，也不在活动栈中混用新旧 JSON。

## 5. 迁移映射表

| 旧路径/命名 | 新路径/命名 | 动作 | 备注 |
|-------------|-------------|------|------|
| 五个 Unity 遥测限速配置 | 无 | delete | 无上限发送不再暴露限速开关 |
| Player 使用 SIM_CAMERA_MAX_HZ | SIM_UNITY_SENSOR_RATE_HZ | rewrite | 采样率与传输解耦 |
| telemetry.json 的 rates、mbit | 无 | delete | 只保留点云编码配置 |
| Uplink 的轮询和限速等待 | 条件变量唤醒 | rewrite | 保留每通道最新值槽 |
| Uplink(settings, encode, log) | Uplink(encode, log) | rewrite | 所有现有调用同步修改 |

### 配套契约同步记录

下列 updated 项是本轮计划同步的契约；实施前先修改其正文。其余候选核对不变。同步门禁未运行，因此不宣称配套契约已经检查通过。

```contract-sync
{
  "baseline": ".artifacts/spec-sync/unity-telemetry-unlimited-20261015.json",
  "baseline_sha256": "55cdfa6c58c6eb689ff86427c4ac30a4ddc948f52f4ef8fc8eb50a71b0599dac",
  "reviews": [
    {"id":"runtime/station-telemetry","clauses":["输入、输出与配置/线上载荷","行为规则/所有权","失败、取消与资源生命周期/生命周期","条款检查判据"],"status":"updated","reason":"按用户要求删除 Unity 通道及聚合限速，明确新值唤醒与有界缓存，线上载荷继续沿用。","evidence":["specs/proposed/inner/station-telemetry.spec.md","drone_projects/l3-dispatcher-planner/ros_packages/telemetry_bridge/src/telemetry_bridge/uplink.py"]},
    {"id":"runtime/unity-k3s-bringup","clauses":["输入、输出与配置/装配与配置","条款检查判据"],"status":"updated","reason":"登记遥测限速键退役和独立 Player 采样配置，配置与启动生命周期继续共用现有入口。","evidence":["specs/proposed/inner/unity-k3s-bringup.spec.md","deployment/tools/station-host-sim.py","deployment/k3s/unity/runtime.defaults.env"]},
    {"id":"runtime","clauses":["不变量","Inner contracts"],"status":"unchanged","reason":"只修订现有两份叶的 Unity 遥测行为，不改变根的资源归属、配置边界或叶登记。","evidence":["specs/proposed/runtime.spec.md","specs/proposed/inner/station-telemetry.spec.md","specs/proposed/inner/unity-k3s-bringup.spec.md"]},
    {"id":"runtime/drone-remote-build","clauses":["范围与非目标"],"status":"unchanged","reason":"本轮只修改 Unity 装配及其独立遥测生产者，真机远端构建入口和 real 清单没有改动。","evidence":["deployment/tools/station-host-drone.py","deployment/tools/drone-host-runtime.py","deployment/k3s/real/runtime.defaults.env"]},
    {"id":"development-workflow/workspace-layout","clauses":["WL2","WL5","WL9"],"status":"unchanged","reason":"沿用 deployment 与 L3 内置子树的现行归属，不移动目录或修改独立 L2/L4 检出。","evidence":["deployment/tools/station-host-sim.py","drone_projects/l3-dispatcher-planner/ros_packages/telemetry_bridge/src/telemetry_bridge/uplink.py"]},
    {"id":"development-workflow/contract-sync","clauses":["§2","§3","R13"],"status":"unchanged","reason":"已按既有规则捕获修改前基线并登记本轮候选，未获检查许可时保留待检查状态。","evidence":[".artifacts/spec-sync/unity-telemetry-unlimited-20261015.json","doc/l3-dispatcher-planner/iteration/design-unity-telemetry-unlimited.md"]},
    {"id":"development-workflow","clauses":["不变量","边界"],"status":"unchanged","reason":"在拥有源码的父仓库修改并保留任务方案，不改变 Git、worktree 或 owner 工作流。","evidence":["doc/l3-dispatcher-planner/iteration/design-unity-telemetry-unlimited.md"]},
    {"id":"development-workflow/l3-coding-style","clauses":["范围与非目标"],"status":"unchanged","reason":"本轮没有 C++ 文件、符号或格式改动，现行 C++ 命名和行为字符串规则继续适用。","evidence":["drone_projects/l3-dispatcher-planner/ros_packages/telemetry_bridge/src/telemetry_bridge/uplink.py"]},
    {"id":"topology/entity-naming","clauses":["§1"],"status":"unchanged","reason":"station-host 入口和 drone-container 装配实体不变，方案及说明只使用角色与相对路径。","evidence":["deployment/tools/station-host-sim.py","deployment/k3s/unity/README.md"]},
    {"id":"topology","clauses":["不变量"],"status":"unchanged","reason":"不改变系统身份或机器配置归属，仍通过现有显式 router 传输遥测。","evidence":["drone_projects/l3-dispatcher-planner/ros_packages/telemetry_bridge/src/telemetry_bridge/uplink.py"]},
    {"id":"observability/log","clauses":["§10","§11"],"status":"unchanged","reason":"仅删除数据遥测限速，错误日志节流保留，fluent-bit、日志 relay 和站端摄入没有改动。","evidence":["drone_projects/l3-dispatcher-planner/ros_packages/telemetry_bridge/src/telemetry_bridge/uplink.py","deployment/k3s/unity/logs.yaml"]},
    {"id":"observability","clauses":["不变量","边界"],"status":"unchanged","reason":"遥测新值唤醒不改变日志与任务结果分离，数据发送成功仍不表示动作成功。","evidence":["specs/proposed/inner/station-telemetry.spec.md"]},
    {"id":"l3-dispatcher/migration-protocol","clauses":["§1","§4"],"status":"unchanged","reason":"本轮直接删除新版限速实现，不迁入旧任务流程、不恢复旧桥或增加新旧转接器。","evidence":["doc/l3-dispatcher-planner/iteration/design-unity-telemetry-unlimited.md","drone_projects/l3-dispatcher-planner/ros_packages/telemetry_bridge/src/telemetry_bridge/uplink.py"]},
    {"id":"l3-dispatcher","clauses":["不变量","边界"],"status":"unchanged","reason":"独立遥测发送不进入 dispatcher core，不改变技能分发、执行缝或 planner 任务职责。","evidence":["specs/proposed/inner/station-telemetry.spec.md"]},
    {"id":"l3-dispatcher/core-boundary","clauses":["B1","B3","B4"],"status":"unchanged","reason":"六态 core 及其端口没有修改，遥测生产者继续独立于任务调度。","evidence":["drone_projects/l3-dispatcher-planner/ros_packages/telemetry_bridge/scripts/telemetry_ros.py"]},
    {"id":"l3-dispatcher/ros-adapter-boundary","clauses":["R1","R2","R6"],"status":"unchanged","reason":"ROS 订阅仍只在 telemetry_ros.py，Uplink 不引入 ROS 类型，topic 和载荷保持原有定义。","evidence":["drone_projects/l3-dispatcher-planner/ros_packages/telemetry_bridge/scripts/telemetry_ros.py","drone_projects/l3-dispatcher-planner/ros_packages/telemetry_bridge/src/telemetry_bridge/uplink.py"]},
    {"id":"l3-dispatcher/package-layout","clauses":["范围与非目标","§3"],"status":"unchanged","reason":"不改 dispatcher 子包、依赖或命名，发送逻辑保留在独立 telemetry_bridge 包。","evidence":["drone_projects/l3-dispatcher-planner/ros_packages/telemetry_bridge/src/telemetry_bridge/uplink.py"]},
    {"id":"l3-dispatcher/execution-seam","clauses":["§2","§4"],"status":"unchanged","reason":"本轮没有动作目标、执行状态、取消或停止接口改动，遥测不持有执行资源。","evidence":["specs/proposed/inner/station-telemetry.spec.md"]},
    {"id":"l3-dispatcher/skill-contract","clauses":["§1","§6"],"status":"unchanged","reason":"本轮不新增或迁移技能，不改变技能资源获取、取消和 disposer 边界。","evidence":["specs/proposed/inner/station-telemetry.spec.md"]},
    {"id":"l3-dispatcher/tool-plane","clauses":["§1","§6","§8"],"status":"unchanged","reason":"遥测限速删除不影响工具注册、租约、owner 门或唯一终态，不增加控制面消费者。","evidence":["specs/proposed/inner/station-telemetry.spec.md"]},
    {"id":"l3-dispatcher/l4-rpc","clauses":["§1","§2","§4"],"status":"unchanged","reason":"仅修改 telemetry 频道的发送节律，RPC 请求、presence/task 与 rpc_outcome 均不修改。","evidence":["specs/proposed/inner/station-telemetry.spec.md"]},
    {"id":"l3-dispatcher/flight-actions","clauses":["§1","§2"],"status":"unchanged","reason":"不改变六项基础动作参数、cmd 输出或完成条件，遥测仍不发送运动命令。","evidence":["specs/proposed/inner/station-telemetry.spec.md"]},
    {"id":"l3-dispatcher/scenegraph","clauses":["范围与非目标"],"status":"unchanged","reason":"不接入场景导航或 scenegraph 数据生产者，沿用现行遥测频道集合。","evidence":["drone_projects/l3-dispatcher-planner/ros_packages/telemetry_bridge/src/telemetry_bridge/uplink.py"]},
    {"id":"l3-dispatcher/tracking","clauses":["范围与非目标"],"status":"unchanged","reason":"不接入 tracking 频道、工具或 TrackTarget 动作，跟踪提案继续保持原有边界。","evidence":["drone_projects/l3-dispatcher-planner/ros_packages/telemetry_bridge/src/telemetry_bridge/uplink.py"]}
  ]
}
```

## 6. 删除清单

| 删除项 | 理由 |
|--------|------|
| 五个 Unity 遥测速度配置及相机 15 Hz 校验 | 用户明确要求不设置传输速度上限 |
| JSON 的 rates、mbit 和 Uplink 的 settings 参数 | 删除限速接口及其唯一调用闭包 |
| 20 ms 轮询、通道最小间隔、按字节等待 | 有新值直接唤醒并发送 |

## 7. 实施步骤（P0/P1/... 分期）

### P0 — 基线、方案与契约

- 范围：先捕获忽略区基线，落盘本方案，再修订两份 runtime 提案叶。
- 行为不变式：不改变其 proposed 生命周期，不把用户本轮代码指令推断为整套运行时提案已采纳。
- 验收：本轮不执行检查；方案登记修改内容和未覆盖项。
- 回退：如需调整，按本轮差异恢复对应正文，不覆盖已有内容。

### P1 — 配置与发送线程

- 范围：默认值、配置校验与生成、Uplink、唯一 ROS 调用方及启动说明。
- 行为不变式：每通道有界最新值；编码仍在后台；新帧不按 Hz 或字节等待；meta 及健康报告保持每秒自然生产；关停唤醒等待线程。
- 验收：后续获明确许可后覆盖突发输入、空闲等待、关停、错误隔离及现有 L4 解码；本轮不新增或读取测试资料。
- 回退：仅在用户要求回退时恢复本轮源码与配置，不运行旧接口兼容层。

## 8. 验收标准

统一声明：未获明确许可，不运行测试、结构门禁、同步门禁、语法验证或运行验收。

- [ ] 后续检查确认五个限速配置及 rates、mbit 已从生产实现删除。
- [ ] 后续行为验证确认有新值即时唤醒，无新值等待，取消唤醒并释放线程及 Zenoh 资源。
- [ ] 后续检查确认 payload、source stamp、坐标系及点云空间配置保持既有定义。
- [ ] 后续获许可运行结构及同步门禁；当前配套契约检查状态为待检查。
- [ ] 后续重新 prepare、启动，再测量实际源、上传、接收频率；本轮不宣称帧率已提升。

本轮已执行的唯一契约工具操作为 `python3 specs/tools/station-host-spec-lint.py --capture-baseline`，带 §5 基线地址和本轮八项 scope；该操作只写基线，不代表门禁通过。

### 执行记录

- 已先落盘本方案，再修改两份提案叶，随后修改 Unity 配置、生成器、发送线程和唯一 ROS 调用方。
- 已从生产实现删除五个限速键、rates、mbit、15 Hz 校验、通道发送间隔、聚合带宽等待和固定 20 ms 轮询；Player 源采样独立配置。
- 已保留每通道最新值、源时戳与坐标校验、原有线上载荷、点云空间配置、BestEffort/Drop 和错误日志节流；关闭通知唤醒等待线程，超时保留传输资源并报告。
- 本轮源码差异为 §10 的八个文件；未修改独立 L2/L4、真机入口或主机本地配置，未提交或推送。
- 仅阅读源码、引用和 Git 差异以完成编辑，没有运行测试、语法验证、结构门禁、同步门禁、构建、部署或帧率测量。配套契约仍为待检查；不能宣称门禁通过或运行限速已解除。
- 运行生效步骤为在允许构建、启停后执行 `make down → make sim-prepare → make up`；不直接修改活动制品、编译成功记录或旧进程。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 编码与现有 router 链路仍有处理成本 | 无上限不等于每个源帧必达 | 保留 BestEffort/Drop 和每通道最新值，不积压历史数据 |
| 原生 Player 仍需有限采样率 | 不能用无限值驱动传感器 | 采样配置独立且正有限，不限制遥测发送 |
| 主机本地保留退役覆盖键或活动旧 JSON | 新旧配置混用 | 旧覆盖键显式报错；重新 prepare 和启动生成配套配置 |
| 尚未执行检查与运行验收 | 不能证明编译或性能结果 | 交付明确待检查、未部署状态，不修改成功制品摘要 |

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|------|------|------|
| doc/l3-dispatcher-planner/iteration/design-unity-telemetry-unlimited.md | add | 先方案、基线、契约处置与执行记录 |
| specs/proposed/inner/station-telemetry.spec.md | edit | Unity 遥测无上限、最新值唤醒与生命周期 |
| specs/proposed/inner/unity-k3s-bringup.spec.md | edit | 删除限速键，采样与传输分离 |
| deployment/k3s/unity/runtime.defaults.env | edit | 删除限速键，独立 Player 采样率 |
| deployment/tools/station-host-sim.py | edit | 配置校验及 JSON 生成闭包 |
| drone_projects/l3-dispatcher-planner/ros_packages/telemetry_bridge/src/telemetry_bridge/uplink.py | edit | 条件变量唤醒、删除限速与固定轮询 |
| drone_projects/l3-dispatcher-planner/ros_packages/telemetry_bridge/scripts/telemetry_ros.py | edit | 同步 Uplink 调用接口 |
| deployment/k3s/unity/README.md | edit | 说明无上限传输、采样配置及重新准备要求 |
