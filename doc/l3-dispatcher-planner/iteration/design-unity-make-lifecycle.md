# Unity make 生命周期与编译缓存收敛方案

> 摘要：以 Exploration 的可靠操作方式为基线，修复制品摘要过宽、重复创建编译 Job 与运行配置混入编译身份的问题；保留真实失败、归属和动态停稳保护。

## 0. 元信息

- 日期：2026-10-15
- 目标路径：`l3-dispatcher-planner/tools/station-host-sim.py`、`bringup/k3s/unity/README.md`
- 状态：代码与配套修订已落盘，同步门禁和行为验证待许可
- owner：运行时装配；配套契约为 runtime/unity-k3s-bringup 提案，不自行变更生命周期。
- 关联文档：`design-unity-startup-config.md`、`design-unity-compile-resources.md`、`design-unity-stop-idempotency.md`

## 1. 背景与动机

前轮已修复配置必填扩大、编译资源不足、Python 导入及站端无登记关闭误报。本轮收敛仍存在的编译缓存边界，避免修改 README 或停止工具后被迫重新编译。

## 2. 现状事实（问题清单）

- `l3-dispatcher-planner/tools/station-host-sim.py:172`：source_digest 混入所有 tools、bringup 及 Unity 客户端内容。
- `l3-dispatcher-planner/tools/station-host-sim.py:437`：prepare 总是删除并重建三个编译 Job，未复用独立成功记录。
- `l3-dispatcher-planner/tools/station-host-sim.py:496`：check_prepared 将完整运行配置摘要视为编译身份。
- `l3-dispatcher-planner/tools/station-host-sim.py:640`：已有无站端登记跳过逻辑，作为本轮起点保留。

## 3. 目标与约束

普通运行配置与编译身份分离；L3、Unity、L2-wire 分别缓存成功记录。编译身份仍包含真实输入、镜像 digest、命令及路径，失败不得留下成功印记。不采用旧版忽略真实失败的分支，不变更消息或领域行为，不新增转接器。
用户本轮没有新增测试、门禁或验收许可；不运行构建、业务启停、测试或同步检查，不宣称合规闭合。

## 4. 方案决策

- 目录：沿用 tools 与 bringup，缓存仅存被忽略的 `.artifacts/k3s-unity/`。
- 命名：使用 component_sources、component_signature 等 snake_case；独立记录为 compile-组件名.json。
- L3 输入：build_ego.sh 实际链接的包、构建脚本及依赖探针；不包括 Markdown、停止脚本、部署清单、运行参数和 Unity 场景客户端。
- Unity 输入：ROS-TCP-Endpoint 与 Unity ROS bridge 包；L2-wire 输入：PositionCommand 源定义和实际 L2 镜像。
- 新 prepared schema=2，记录 components；删除旧整体 source/config 编译身份，不保留 schema=1 转接口。旧记录需一次显式 prepare。
- prepare 每组件判定输入、镜像、命令和路径，缓存及必要产物齐全才跳过；重建前失效该组件印记，成功且输入未变才落盘。
- up 根据当前运行配置生成遥测/Player 配置；运行参数变化仍受端口和活动资源归属约束，但不因此重新编译。
- 保留既有自动节点、实例命名、PUBLIC_ZENOHD_ROUTER、可选地面高度、独立编译资源、Python 3.8 修复及无登记关闭行为。

## 5. 迁移映射表

- source_digest → component_sources/component_signature：拆分并删除整体摘要接口。
- prepared schema=1 → schema=2：直接替换；不自动把旧记录认作新缓存。
- 全量 prepare → 按组件复用；完整运行配置比较 → 实际构建身份比较。

### 配套契约同步记录

修改前已捕获主机忽略区基线，现有暂存修改全部作为起点。下方按绑定和反向依赖记录处置；同步门禁未获许可，记录不代表门禁通过。

```contract-sync
{
  "baseline": ".artifacts/spec-sync/unity-make-lifecycle-20261015.json",
  "baseline_sha256": "0d5c4858b60281ed53b264c9a289f930e86911e37282dce1b090f974e81270d1",
  "reviews": [
    {
      "id": "development-workflow",
      "clauses": [
        "边界"
      ],
      "status": "unchanged",
      "reason": "本轮只修改运行时缓存与方案记录，不改变源码 owner、Git 或工作树边界。",
      "evidence": [
        "specs/implemented/development-workflow.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-make-lifecycle.md"
      ]
    },
    {
      "id": "development-workflow/contract-sync",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "按现有要求捕获修改前基线并记录绑定及反向依赖处置，未修改同步规则；同步门禁尚未获准执行。",
      "evidence": [
        "specs/implemented/inner/spec-change-sync.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-make-lifecycle.md"
      ]
    },
    {
      "id": "l3-dispatcher",
      "clauses": [
        "边界"
      ],
      "status": "unchanged",
      "reason": "只调整部署与制品装配，不改变 dispatcher 六态、技能分发、执行职责或终态规则。",
      "evidence": [
        "specs/implemented/l3-dispatcher.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-make-lifecycle.md"
      ]
    },
    {
      "id": "l3-dispatcher/core-boundary",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "构建缓存未修改 core 源码，任务队列、六态 FSM 与分发禁令保持原要求。",
      "evidence": [
        "specs/implemented/inner/l3-core-boundary.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-make-lifecycle.md"
      ]
    },
    {
      "id": "l3-dispatcher/execution-seam",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "独立构建缓存仍包含完整 planner_execution 包及生成消息，不改变原生 action、停稳或取消行为。",
      "evidence": [
        "specs/implemented/inner/l3-execution-seam.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-make-lifecycle.md"
      ]
    },
    {
      "id": "l3-dispatcher/flight-actions",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "地面参数可选和无登记停止已是基线行为，本轮不改变起降转交、返航原点或 cmd 完成语义。",
      "evidence": [
        "specs/implemented/inner/flight-actions.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-make-lifecycle.md"
      ]
    },
    {
      "id": "l3-dispatcher/l4-rpc",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "PUBLIC_ZENOHD_ROUTER 的既有装配保持，运行配置重生成不改变 RPC 信封、presence 或连接规则。",
      "evidence": [
        "specs/implemented/inner/l3-l4-rpc.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-make-lifecycle.md"
      ]
    },
    {
      "id": "l3-dispatcher/migration-protocol",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "本轮方案比较部署流程但不迁入任何旧技能或领域逻辑，保留禁止转接器及旧协议退役边界。",
      "evidence": [
        "specs/implemented/inner/l3-migration-protocol.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-make-lifecycle.md"
      ]
    },
    {
      "id": "l3-dispatcher/package-layout",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "dispatcher 子包路径与源码命名均保持，新增缓存函数仅在既有 station-host 工具内。",
      "evidence": [
        "specs/implemented/inner/l3-package-layout.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-make-lifecycle.md"
      ]
    },
    {
      "id": "l3-dispatcher/ros-adapter-boundary",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "仅修改宿主机编译装配，未移动 ROS 收发或改变消息翻译、共享状态与端口边界。",
      "evidence": [
        "specs/implemented/inner/l3-ros-adapter-boundary.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-make-lifecycle.md"
      ]
    },
    {
      "id": "l3-dispatcher/scenegraph",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "提案能力和所有权保持，缓存只覆盖已有实际构建包，不接入新场景工具或修改状态机。",
      "evidence": [
        "specs/proposed/inner/l3-scenegraph.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-make-lifecycle.md"
      ]
    },
    {
      "id": "l3-dispatcher/skill-contract",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "不改技能注册、生命周期或宿主协议，缓存粒度不成为新的技能或任务身份。",
      "evidence": [
        "specs/implemented/inner/l3-skill-contract.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-make-lifecycle.md"
      ]
    },
    {
      "id": "l3-dispatcher/tool-plane",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "保留真实入口依赖检查及所有任务面运行探针，不改变工具发现、准入、租约和取消协议。",
      "evidence": [
        "specs/implemented/inner/l3-tool-plane.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-make-lifecycle.md"
      ]
    },
    {
      "id": "l3-dispatcher/tracking",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "仍将 Elastic 及 dispatcher 跟踪源码计入 L3 输入，不改变跟踪动作、地图读取或提案采纳状态。",
      "evidence": [
        "specs/proposed/inner/l3-tracking.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-make-lifecycle.md"
      ]
    },
    {
      "id": "observability",
      "clauses": [
        "边界"
      ],
      "status": "unchanged",
      "reason": "只改构建记录及缓存命中输出，不改变日志面职责、真实证据及运行状态判定。",
      "evidence": [
        "specs/implemented/observability.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-make-lifecycle.md"
      ]
    },
    {
      "id": "observability/log",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "编译缓存命中与失败提示为运维输出，不改变机上日志协议、事件字段、日志生产者或停止记录能力。",
      "evidence": [
        "specs/implemented/inner/observability-log.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-make-lifecycle.md"
      ]
    },
    {
      "id": "runtime",
      "clauses": [
        "边界"
      ],
      "status": "unchanged",
      "reason": "仍使用同源构建镜像摘要及固定挂载路径，不改变 namespace 归属与启动安全门，仅收窄编译身份。",
      "evidence": [
        "specs/proposed/runtime.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-make-lifecycle.md"
      ]
    },
    {
      "id": "runtime/unity-k3s-bringup",
      "clauses": [
        "输入、输出与配置",
        "失败、取消与资源生命周期"
      ],
      "status": "updated",
      "reason": "已同步 UB4–UB7：组件构建身份、独立缓存、运行配置分离及无登记停止要求；提案生命周期保持不变。",
      "evidence": [
        "specs/proposed/inner/unity-k3s-bringup.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-make-lifecycle.md"
      ]
    },
    {
      "id": "topology",
      "clauses": [
        "边界"
      ],
      "status": "unchanged",
      "reason": "仍使用工作区身份隔离资源，机器参数保留在本地忽略区；无新增公开机器值。",
      "evidence": [
        "specs/implemented/topology.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-make-lifecycle.md"
      ]
    },
    {
      "id": "topology/entity-naming",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "启动器仍由 station-host 执行，保留 Entity、Invoked 头和既有文件名，缓存组件名不引入执行实体。",
      "evidence": [
        "specs/implemented/inner/entity-naming.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-make-lifecycle.md"
      ]
    }
  ]
}
```

## 6. 删除清单

删除整体 source_digest、prepare 的全局源码摘要及 check_prepared 的完整运行配置相等要求。删除旧 prepared schema 的生产和消费，不恢复退役目标或消息桥。

## 7. 实施步骤

P0：读取契约、捕获基线、落盘方案。P1：先修订 runtime 提案的身份、缓存与无登记停止要求。P2：替换缓存装配，保持编译失败和真实安全门。P3：同步操作说明与本轮处置记录。
回退仅撤销本轮差异，不覆盖既有暂存内容；回退后重新 prepare 生成对应版本记录，不伪造缓存。

## 8. 验收标准

待明确许可后检查 README/停止逻辑/遥测频率变化不失效编译；L3 源码变化仅重建 L3；Unity bridge 变化仅重建 Unity；镜像与消息变化拒绝旧记录；构建失败印记失效、重试保留已成功组件。
本轮仅捕获基线，不运行 --list-impacts、--sync-plan、结构门禁、测试、构建或启停验收。配套契约同步待检查，运行行为待验证。

## 9. 风险与对策

范围收窄可能漏掉依赖：按 build_ego.sh 链接清单显式列出全部包，缺目录即失败，包含 CMake、package.xml 和构建脚本。独立缓存只在镜像、命令、路径和输入均一致时复用；不由 Job 存在推断成功。旧记录一次重建，后续增量复用。

## 10. 修改点清单汇总

- tools/station-host-sim.py：组件输入与缓存、schema=2、运行配置独立生成。
- bringup/k3s/unity/README.md：首次升级和增量准备说明。
- specs/proposed/inner/unity-k3s-bringup.spec.md：同步缓存和无登记停止要求。
- 本方案：同步记录、实际检查范围和剩余条件。


### 本轮交付记录

已将整体编译身份替换为独立组件签名和成功记录，启动前生成当前运行配置。
缓存签名包括实际构建包、镜像、命令及路径；L2-wire 同时关联生成后的 PositionCommand 内容。
现有配置收敛、8 GiB 编译资源、Python 3.8 注解及真实模块导入修复、无站端登记关闭逻辑经源码核对保留。
只执行基线捕获和源码/契约阅读；未运行同步门禁、结构门禁、测试、构建或业务启停。
上述 unchanged 为源码和条款处置记录，不代表同步门禁已通过或运行行为已验收。
