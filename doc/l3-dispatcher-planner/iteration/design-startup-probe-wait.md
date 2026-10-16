# 仿真启动就绪等待调整方案

> 摘要：调整 `deployment/tools/station-host-sim.py` 的启动等待，使 Deployment
> 就绪后才执行容器内业务探针，消除正常创建期间的 `container not found` 提示。
> 依据为本轮启动输出及运行时装配提案，保留工作区已有遥测改动。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-10-15 |
| 目标路径 | `deployment/tools/station-host-sim.py` |
| 状态 | in-progress；代码及文档编辑完成，结构与同步检查通过，运行验收未执行 |
| 关联文档 | [运行时装配提案](../../../specs/proposed/inner/unity-k3s-bringup.spec.md)、[实现变更同步契约](../../../specs/implemented/inner/spec-change-sync.spec.md) |

## 1. 背景与动机

用户报告每次完整启动时，master、odom、planner、telemetry 先出现
`container not found`，随后业务栈就绪。本轮起初获准调整代码，未获测试、门禁、
部署或重启许可；随后用户询问契约是否存在冲突，本轮据此开展契约文档的结构、
同步与条款一致性检查，许可不扩展为业务测试或启停服务。
修复启动探测抢跑及其输出，不改变业务依赖顺序。

## 2. 现状事实（问题清单）

- `deployment/tools/station-host-sim.py#L265-L274`：`create` 在资源创建请求完成后
  返回，没有等待实际容器可执行。
- `deployment/tools/station-host-sim.py#L558-L579`：`wait_probe` 首次循环立即
  `kubectl exec`，失败后原样打印错误，每三秒重试。
- `deployment/tools/station-host-sim.py#L603-L619`：启动依次等待 master、odom、
  sensors、planner、task、telemetry、logs，只有日志部署显式等待 rollout。
- `deployment/tools/station-host-sim.py#L343-L345`：各业务 Deployment 已有
  readinessProbe，可以复用其就绪状态。
- 修改前 `deployment/tools/station-host-sim.py` 和运行时装配提案已有遥测相关
  未提交改动；本轮基线将这些内容作为起点，不覆盖或归入本轮修改。

## 3. 目标与约束

- **目标**：先等待部署就绪，再复核业务；正常创建期间显示等待状态，失败保留诊断。
- **非目标**：不调整 ROS 业务、镜像、配置默认值、依赖顺序及站端服务。
- **硬边界**：不新增转接器，不保留被替代的直接启动探测路径，不使用固定延迟
  代替就绪条件；不运行业务测试或部署，不读取测试资料。文档检查限于契约结构、
  配套同步与本次条款一致性，不据此声明运行验收。

## 4. 方案决策

- **目标目录树**：沿用现有归属，不拆目录或增加运维入口。

  ```text
  deployment/tools/
    station-host-sim.py
  specs/proposed/inner/
    unity-k3s-bringup.spec.md
  doc/l3-dispatcher-planner/iteration/
    design-startup-probe-wait.md
  ```

- **命名规范表**：

  | 类型 | 规范 | 示例 |
  |------|------|------|
  | 运维文件 | 沿用执行实体前缀 | `station-host-sim.py` |
  | 方法 | 沿用 snake_case 动词命名 | `wait_probe`、`exec_probe` |
  | 等待预算 | 使用现有秒单位配置和单调时钟 | `SIM_READY_TIMEOUT_S`、`deadline` |

- **接口形态**：`wait_probe` 先执行对应 Deployment 的 `rollout status`，再进入
  现有业务探针循环；两阶段共用一次等待截止时间。`exec_probe` 增加内部可选
  `timeout` 参数，默认仍为 25 秒；启动调用按剩余预算限制每次探针。
  Kubernetes 自身的 readinessProbe 继续按原配置运行，和编排入口后续主动执行
  的 exec 业务复核属于不同机制，不要求 readinessProbe 等到 rollout 之后执行。
- **输出与异常**：部署等待开始时输出正常就绪等待提示；rollout 非零或超时保留
  命令诊断并失败。就绪后若容器恰好重启，特定 `container not found` 仅在重试
  提示中转为“容器正在启动或重启”，原始信息仍保留在最终超时详情。
- **旧接口 → 删除**：直接进入首次 `exec` 的启动路径由阶段等待替换，不留备用路径。

## 5. 迁移映射表

| 旧路径/命名 | 新路径/命名 | 动作 | 备注 |
|-------------|-------------|------|------|
| `Stack.wait_probe` 立即执行业务探针 | 同方法先等待 rollout 后复核 | rewrite | 不改变启动调用顺序 |
| `Stack.exec_probe` 固定命令超时 | 同方法接受剩余等待预算 | rewrite | 其他调用沿用默认值 |
| 创建期直接输出原始错误 | 正常就绪等待及重启状态提示 | rewrite | 超时详情保留诊断 |

### 配套契约同步记录

基线仅捕获本轮三个路径。候选按路径绑定和依赖关系人工登记；方案目录的迁移规程
绑定带来 L3 领域候选，其实现文件和业务条款均不在本轮修改范围。下列处置不代表
结构或同步门禁通过；处置已按本轮两个方法、UB10 及方案新增的差异更新，
检查状态归 §8、§10。

```contract-sync
{
  "baseline": ".artifacts/spec-sync/startup-probe-wait-20261015.json",
  "baseline_sha256": "644a499c1229076baed161ae7ac8d5cc15f884d1573adc93ad1a61d9070dc902",
  "reviews": [
    {"id": "runtime/unity-k3s-bringup", "clauses": ["UB10", "生命周期"], "status": "updated", "reason": "已补充 UB10 及检查判据，明确区分 Kubernetes 就绪探针与编排入口 exec 复核，代码共用预算并保留诊断，提案状态不变。", "evidence": ["deployment/tools/station-host-sim.py", "specs/proposed/inner/unity-k3s-bringup.spec.md"]},
    {"id": "runtime", "clauses": ["不变量", "Inner contracts"], "status": "unchanged", "reason": "等待阶段细节由现有装配叶拥有，根的资源归属、生命周期和叶登记均无需改变。", "evidence": ["specs/proposed/runtime.spec.md", "deployment/tools/station-host-sim.py"]},
    {"id": "runtime/drone-remote-build", "clauses": ["范围与非目标", "编译与运行"], "status": "unchanged", "reason": "因工作区布局依赖进入候选，本轮只改同机仿真入口，不修改设备投放或真机等待。", "evidence": ["specs/proposed/inner/drone-remote-build.spec.md", "deployment/tools/station-host-sim.py"]},
    {"id": "development-workflow/contract-sync", "clauses": ["R2", "R5", "R13"], "status": "unchanged", "reason": "使用已有基线和同步记录格式，原有未提交内容作为起点；用户后续要求确认契约冲突后执行文档范围的同步检查。", "evidence": ["doc/l3-dispatcher-planner/iteration/design-startup-probe-wait.md", "specs/implemented/inner/spec-change-sync.spec.md"]},
    {"id": "development-workflow/workspace-layout", "clauses": ["WL5", "WL7"], "status": "unchanged", "reason": "仿真启停逻辑仍归部署工具，配套方案仍归既有迭代目录，不移动代码或制品路径。", "evidence": ["deployment/tools/station-host-sim.py", "doc/l3-dispatcher-planner/iteration/design-startup-probe-wait.md"]},
    {"id": "development-workflow", "clauses": ["不变量", "Inner contracts"], "status": "unchanged", "reason": "现有源码归属及工作流边界保持一致，不创建分支、提交、钩子或新的工作流规范。", "evidence": ["specs/implemented/development-workflow.spec.md", "doc/l3-dispatcher-planner/iteration/design-startup-probe-wait.md"]},
    {"id": "topology/entity-naming", "clauses": ["§2"], "status": "unchanged", "reason": "保留 station-host 文件前缀及 Entity、Invoked 头，不新增实体或运维脚本入口。", "evidence": ["deployment/tools/station-host-sim.py", "specs/implemented/inner/entity-naming.spec.md"]},
    {"id": "topology", "clauses": ["不变量", "Inner contracts"], "status": "unchanged", "reason": "等待逻辑不改变执行实体或配置身份，方案只使用仓库相对路径和角色名。", "evidence": ["specs/implemented/topology.spec.md", "doc/l3-dispatcher-planner/iteration/design-startup-probe-wait.md"]},
    {"id": "l3-dispatcher/migration-protocol", "clauses": ["§4", "§7"], "status": "unchanged", "reason": "因方案目录绑定进入候选；本轮为仿真编排修复，不研究或迁移旧版单元，不新增兼容层。", "evidence": ["doc/l3-dispatcher-planner/iteration/design-startup-probe-wait.md", "deployment/tools/station-host-sim.py"]},
    {"id": "l3-dispatcher/core-boundary", "clauses": ["§1", "§2"], "status": "unchanged", "reason": "迁移规程反向依赖引入候选，修改不进入 core，六态、分发职责与未注册失败语义不变。", "evidence": ["specs/implemented/inner/l3-core-boundary.spec.md", "deployment/tools/station-host-sim.py"]},
    {"id": "l3-dispatcher/execution-seam", "clauses": ["§3", "§4"], "status": "unchanged", "reason": "启动业务复核沿用现有探针，不修改动作会话、停稳门、停止取消或执行资源生命周期。", "evidence": ["specs/implemented/inner/l3-execution-seam.spec.md", "deployment/tools/station-host-sim.py"]},
    {"id": "l3-dispatcher/l4-rpc", "clauses": ["§2", "§4"], "status": "unchanged", "reason": "继续使用原 task 探针与站端启动顺序，RPC 信封、presence、租约和终态投递均未变更。", "evidence": ["specs/implemented/inner/l3-l4-rpc.spec.md", "deployment/tools/station-host-sim.py"]},
    {"id": "l3-dispatcher/package-layout", "clauses": ["§1", "§3"], "status": "unchanged", "reason": "修改仅发生在部署工具的原方法，不改变 dispatcher 子包、模块命名或导入方向。", "evidence": ["specs/implemented/inner/l3-package-layout.spec.md", "deployment/tools/station-host-sim.py"]},
    {"id": "l3-dispatcher/ros-adapter-boundary", "clauses": ["R1", "R6"], "status": "unchanged", "reason": "等待仍由主机 kubectl 和既有探针执行，不向领域层引入 ROS 收发或更改消息名称。", "evidence": ["specs/implemented/inner/l3-ros-adapter-boundary.spec.md", "deployment/tools/station-host-sim.py"]},
    {"id": "l3-dispatcher/skill-contract", "clauses": ["§2", "§6"], "status": "unchanged", "reason": "方案目录依赖传播进入候选，技能身份、宿主端口、注册逆操作和生命周期均保持原样。", "evidence": ["specs/implemented/inner/l3-skill-contract.spec.md", "deployment/tools/station-host-sim.py"]},
    {"id": "l3-dispatcher/tool-plane", "clauses": ["§1", "§9"], "status": "unchanged", "reason": "部署就绪仍只作启动条件，不作为工具完成依据；不修改生产集合、准入或完成语义。", "evidence": ["specs/implemented/inner/l3-tool-plane.spec.md", "deployment/tools/station-host-sim.py"]},
    {"id": "l3-dispatcher/flight-actions", "clauses": ["§1", "§2"], "status": "unchanged", "reason": "业务探针仍不发送运动，本轮不涉及基础飞行参数、原点、起降出口或动作终态。", "evidence": ["specs/implemented/inner/flight-actions.spec.md", "deployment/tools/station-host-sim.py"]},
    {"id": "l3-dispatcher/scenegraph", "clauses": ["范围与非目标"], "status": "unchanged", "reason": "由 L3 依赖传播进入候选，场景图能力及其加载、查询、写入归属不受部署等待影响。", "evidence": ["specs/proposed/inner/l3-scenegraph.spec.md", "deployment/tools/station-host-sim.py"]},
    {"id": "l3-dispatcher/tracking", "clauses": ["范围与非目标", "归属与依赖"], "status": "unchanged", "reason": "没有修改 tracking 装配、观测或连续执行，默认仿真启动不增加跟踪入口或注册能力。", "evidence": ["specs/proposed/inner/l3-tracking.spec.md", "deployment/tools/station-host-sim.py"]},
    {"id": "l3-dispatcher", "clauses": ["不变量", "边界"], "status": "unchanged", "reason": "本轮代码归部署编排边界，不修改调度、执行缝或运动规划职责及其叶登记。", "evidence": ["specs/implemented/l3-dispatcher.spec.md", "deployment/tools/station-host-sim.py"]},
    {"id": "observability/log", "clauses": ["范围与非目标"], "status": "unchanged", "reason": "只调整 station-host 启动提示，不改变 L3 进程日志信封、采集器、中继或站端摄入。", "evidence": ["specs/implemented/inner/observability-log.spec.md", "deployment/tools/station-host-sim.py"]},
    {"id": "observability", "clauses": ["不变量", "边界"], "status": "unchanged", "reason": "日志平面与部署工作流边界保持一致，已有日志接收探针继续独立复核数据。", "evidence": ["specs/implemented/observability.spec.md", "deployment/tools/station-host-sim.py"]}
  ]
}
```

## 6. 删除清单

| 删除项 | 理由 |
|--------|------|
| 创建 Deployment 后立即执行首次业务探针的路径 | 容器尚未创建时必然存在探测抢跑窗口 |
| 仅对重启竞态原样打印 `container not found` 的重试提示 | 用正常等待状态表达，原始错误仍保留用于超时诊断 |

## 7. 实施步骤（P0/P1/P2 分期）

### P0 — 基线与方案

- 范围：捕获任务基线，形成当前方案和配套契约处置。
- 行为不变式：已有未提交改动全部作为本轮起点保留。
- 验收：不运行检查；只记录基线捕获命令和摘要。
- 回退：不删除或覆盖既有方案和用户修改。

### P1 — 契约与代码

- 范围：在装配提案补充 UB10，然后改 `wait_probe` 和 `exec_probe`。
- 行为不变式：依赖顺序、业务探针及安全关闭流程不变，阶段共享等待预算。
- 验收：待取得许可后按 §8 执行；本轮不运行。
- 回退：仅撤销本轮两个方法及 UB10 的差异，保留基线前遥测改动。

### P2 — 交付记录

- 范围：登记实际修改及检查缺口，不自行标记已验收。
- 行为不变式：不部署、不重启、不提交、不推送。
- 验收：初次交付时结构和同步门禁保留待检查；用户随后询问契约冲突后，补做文档检查。
- 回退：保留可追溯任务基线及本方案。

本轮执行记录：P0 已捕获基线并先行落盘方案；P1 已先更新装配提案 UB10，再调整
`wait_probe` 与 `exec_probe`；P2 已补充当前处置和交付状态。后续文档复核明确 UB10
对 Kubernetes 自身 readinessProbe 与编排入口 exec 复核的区分，避免时序表述歧义。
未执行任何业务程序、测试、构建、部署、重启或运行验收。

## 8. 验收标准

**统一声明**：按 `AGENTS.md` §9 和 `specs/README.md` C3，不运行业务测试或运行
验收，不读取测试资料。用户后续询问契约冲突，授权范围按契约文档检查处理。

- 待许可：从关闭状态启动时，先显示部署就绪等待，再执行原业务探针。
- 待许可：master、odom、planner、telemetry 的正常创建期不显示 `container not found`。
- 待许可：rollout 失败、业务复核失败或容器重启未恢复时，以非零结束并保留诊断。
- 待许可：两阶段及每次业务探针均受同一次等待预算约束。
- 已执行：文档结构和本方案同步检查通过；不将此结果作为运行效果或外部仓库验收证据。

已执行的基线捕获命令为：

```sh
python3 specs/tools/station-host-spec-lint.py --capture-baseline .artifacts/spec-sync/startup-probe-wait-20261015.json --scope deployment/tools/station-host-sim.py --scope specs/proposed/inner/unity-k3s-bringup.spec.md --scope doc/l3-dispatcher-planner/iteration/design-startup-probe-wait.md
```

该模式用于写入任务起点，不作为前置结构门禁或同步门禁通过的结论。

文档检查命令：

```sh
python3 specs/tools/station-host-spec-lint.py --sync-plan doc/l3-dispatcher-planner/iteration/design-startup-probe-wait.md
```

结果：退出码 0；读取 42 条记录，未发现结构错误，本轮 3 个变更文件、22 个候选
契约的处置记录通过同步检查。人工文档复核覆盖 UB10、运行时父根不变量、原启动
顺序和就绪判据，未发现本次修改引入的实质条款冲突；UB10 的探针时序歧义已澄清。
该结论限定于本轮配套契约，不构成整个注册表所有业务条款无冲突的结论。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| readinessProbe 首次调度有周期 | 启动可能多等一个探针周期 | 沿用已有配置，不添加固定启动延迟 |
| rollout 通过后容器恰好重启 | exec 仍可能遇到暂态失败 | 保留重试，正常显示重启等待，超时保留原始错误 |
| 两阶段分别使用完整预算 | 实际等待被翻倍 | 共用单调截止时间，按剩余预算限制探针和睡眠 |
| 覆盖已有遥测调整 | 混入其他任务变更 | 基线固定已有内容，只编辑本轮方法及 UB10 |
| 运行验收尚未获许可 | 缺少实际启动效果证据 | 文档检查与运行证据分开，保持运行验收未执行的状态 |

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|------|------|------|
| `deployment/tools/station-host-sim.py` | rewrite | 已调整两阶段等待、剩余预算、失败详情及重启提示 |
| `specs/proposed/inner/unity-k3s-bringup.spec.md` | rewrite | 已补充 UB10 及对应检查判据，保持提案状态 |
| 当前方案 | add | 先方案后改码，记录起点、配套处置和许可边界 |

本轮代码及配套文档编辑已完成，已有遥测改动保留。实际查看范围为任务文件差异及
配套契约归属；使用 `git diff`、`git status --short` 和源码读取整理编辑结果。
初次交付未执行结构或同步门禁；用户后续询问契约冲突后，已执行 §8 的
`--sync-plan`，其同时检查注册表结构与本轮同步记录，结果通过。
未执行 `--list-impacts`、语法检查、业务测试或 `make up`。本轮文档检查已通过，
运行效果未验收，不宣称运行合规；方案继续保持 in-progress。
