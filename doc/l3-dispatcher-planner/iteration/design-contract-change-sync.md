# 实现变更与配套契约同步方案

> 摘要：补齐实现路径到契约的关联、依赖反查、任务差异与同步处置门禁；不修改或审查业务实现。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-10-14 |
| 目标路径 | `specs/`、根 `AGENTS.md`、客户端引导及迭代模板 |
| 状态 | done（结构与配套同步记录检查通过，不含业务正确性） |
| 关联文档 | `specs/README.md`、`specs/implemented/development-workflow.spec.md` |

## 1. 背景与动机

用户要求实现改动时同步处理配套契约。现有结构门禁无法检测未被修改的关联契约，需要将影响识别和逐项处置变为交付条件。

## 2. 现状事实（问题清单）

- `specs/README.md:184` 的 A1 主要在契约文件任务触发，没有要求所有实现修改生成契约影响清单。
- `specs/tools/station-host-spec-lint.py:367` 的入口仅接收仓库路径，没有任务差异和处置记录输入。
- `doc/l3-dispatcher-planner/iteration/_TEMPLATE.md:62` 的迁移映射没有配套契约逐项处置记录。
- 17 份现有叶契约有“归属与依赖”正文，但没有统一的可读关联数据块。

## 3. 目标与约束

- 目标：实现、配置、消息、接口、目录及契约改动均触发影响核对，遗漏处置阻止交付。
- 非目标：不审查业务规则正确性，不修改业务代码，不运行业务测试、构建或部署，不提交或安装钩子。
- 硬边界：元数据不复制业务要求；不新增新旧接口转接层；保留既有工作区改动。
- 许可：沿用用户对文档合规检查的明确授权；只运行文档及同步记录检查。

## 4. 方案决策

- 新增 `specs/implemented/inner/spec-change-sync.spec.md`，ID 为 `development-workflow/contract-sync`，由开发工作流根登记。
- 现行与提案叶在归属章节声明一个 `contract-links` JSON 块，包含 implementation 路径模式及 depends_on 契约 ID。
- 复用原生静态入口，新增基线捕获、候选影响报告和同步计划检查模式，不创建旧脚本包装。
- 基线只写 Git 忽略区，保存明确任务范围内的文件 SHA-256、当前提交和关联图；不覆盖已有基线。
- 比较基线与结束时文件指纹，覆盖新增、删除、重命名两端及未跟踪文件；初始未提交且未继续改变的文件不计入本轮。
- 候选集由两版关联图的路径匹配、契约自身变更、反向依赖传递及父根登记构成；不从父根展开全部同级叶。
- 方案内 `contract-sync` JSON 记录 baseline、baseline_sha256、reviews。每项含 id、clauses、status、reason、evidence。
- status 只允许 updated、unchanged、pending；pending、漏项、虚报更新、无证据或未映射文件均失败。无需修改的契约仍须给出理由。
- 门禁证明覆盖与记录完整性，不证明业务处置充分或跨仓库实现已同步；真正受影响的外部 owner 仍须在方案登记剩余工作。

## 5. 迁移映射表

| 旧位置 | 新位置 | 动作 |
|----|----|----|
| README 中笼统同步要求 | 新同步叶契约 | 详细机制归唯一叶所有 |
| 叶契约非结构化归属说明 | 原章节追加关联块 | 保留原业务正文 |
| 仅文档任务的 AI 入口 | AGENTS 与客户端引导 | 扩大至实现及配置任务 |
| 方案迁移表 | §5 追加同步清单 | 保留原有 §0–§10 |
| 只读结构门禁 | 同入口新增明确模式 | 无转接器 |

### 配套契约同步记录

```contract-sync
{
  "baseline": ".artifacts/spec-sync/contract-change-sync-20261014.json",
  "baseline_sha256": "d6e43658a19029c9fdf91049b51fcce57a7215eb7fc4be6faf19fc5ca5edd564",
  "reviews": [
    {
      "id": "development-workflow",
      "clauses": [
        "Inner contracts"
      ],
      "status": "updated",
      "reason": "新增同步叶的登记，保持开发工作流原有系统边界，具体机制归新增叶唯一所有。",
      "evidence": [
        "specs/implemented/development-workflow.spec.md",
        "doc/l3-dispatcher-planner/iteration/design-contract-change-sync.md"
      ]
    },
    {
      "id": "development-workflow/contract-sync",
      "clauses": [
        "输入、输出与配置",
        "行为规则",
        "归属与依赖/变更关联",
        "条款检查判据"
      ],
      "status": "updated",
      "reason": "新增路径绑定、任务指纹基线、反向依赖和逐项处置机制，并与实际门禁及方案模板同步。",
      "evidence": [
        "specs/implemented/inner/spec-change-sync.spec.md",
        "doc/l3-dispatcher-planner/iteration/design-contract-change-sync.md"
      ]
    },
    {
      "id": "development-workflow/l3-coding-style",
      "clauses": [
        "归属与依赖/变更关联"
      ],
      "status": "updated",
      "reason": "只追加实际C++源码后缀的关联范围，原命名、单位和格式条款全文保持。",
      "evidence": [
        "specs/implemented/inner/l3-coding-style.spec.md",
        "doc/l3-dispatcher-planner/iteration/design-contract-change-sync.md"
      ]
    },
    {
      "id": "l3-dispatcher",
      "clauses": [
        "Inner contracts"
      ],
      "status": "unchanged",
      "reason": "子叶仅追加关联元数据，身份、生命周期和文件路径未变，现有子契约登记无需调整。",
      "evidence": [
        "specs/implemented/l3-dispatcher.spec.md",
        "doc/l3-dispatcher-planner/iteration/design-contract-change-sync.md"
      ]
    },
    {
      "id": "l3-dispatcher/core-boundary",
      "clauses": [
        "归属与依赖/变更关联"
      ],
      "status": "updated",
      "reason": "只追加core及装配根的路径绑定与文档依赖索引，六态和原有禁令正文保持。",
      "evidence": [
        "specs/implemented/inner/l3-core-boundary.spec.md",
        "doc/l3-dispatcher-planner/iteration/design-contract-change-sync.md"
      ]
    },
    {
      "id": "l3-dispatcher/execution-seam",
      "clauses": [
        "归属与依赖/变更关联"
      ],
      "status": "updated",
      "reason": "只登记共享执行、原生消息和后端路径关联，完成门、配置及停止要求正文保持。",
      "evidence": [
        "specs/implemented/inner/l3-execution-seam.spec.md",
        "doc/l3-dispatcher-planner/iteration/design-contract-change-sync.md"
      ]
    },
    {
      "id": "l3-dispatcher/flight-actions",
      "clauses": [
        "归属与依赖/变更关联"
      ],
      "status": "updated",
      "reason": "只追加飞行家族、启动配置及起降消息的路径关联，动作参数和完成要求正文保持。",
      "evidence": [
        "specs/implemented/inner/flight-actions.spec.md",
        "doc/l3-dispatcher-planner/iteration/design-contract-change-sync.md"
      ]
    },
    {
      "id": "l3-dispatcher/l4-rpc",
      "clauses": [
        "归属与依赖/变更关联"
      ],
      "status": "updated",
      "reason": "只登记当前工具面传输、租约与运行模块路径，RPC信封与生命周期正文保持；不声明站端同步验收。",
      "evidence": [
        "specs/implemented/inner/l3-l4-rpc.spec.md",
        "doc/l3-dispatcher-planner/iteration/design-contract-change-sync.md"
      ]
    },
    {
      "id": "l3-dispatcher/migration-protocol",
      "clauses": [
        "归属与依赖/变更关联"
      ],
      "status": "updated",
      "reason": "只追加迭代方案及台账的关联数据，迁移裁决、准入和交付要求正文保持。",
      "evidence": [
        "specs/implemented/inner/l3-migration-protocol.spec.md",
        "doc/l3-dispatcher-planner/iteration/design-contract-change-sync.md"
      ]
    },
    {
      "id": "l3-dispatcher/package-layout",
      "clauses": [
        "归属与依赖/变更关联"
      ],
      "status": "updated",
      "reason": "只追加dispatcher子树与已引用契约的关联索引，平面、命名与依赖方向正文保持。",
      "evidence": [
        "specs/implemented/inner/l3-package-layout.spec.md",
        "doc/l3-dispatcher-planner/iteration/design-contract-change-sync.md"
      ]
    },
    {
      "id": "l3-dispatcher/ros-adapter-boundary",
      "clauses": [
        "归属与依赖/变更关联"
      ],
      "status": "updated",
      "reason": "只增加dispatcher及ROS适配文件的路径关联，收发隔离与共享状态要求正文保持。",
      "evidence": [
        "specs/implemented/inner/l3-ros-adapter-boundary.spec.md",
        "doc/l3-dispatcher-planner/iteration/design-contract-change-sync.md"
      ]
    },
    {
      "id": "l3-dispatcher/scenegraph",
      "clauses": [
        "归属与依赖/变更关联"
      ],
      "status": "updated",
      "reason": "仅为现有场景家族设计追加路径与文档依赖，维持未采纳状态；未变更外部builder条款。",
      "evidence": [
        "specs/proposed/inner/l3-scenegraph.spec.md",
        "doc/l3-dispatcher-planner/iteration/design-contract-change-sync.md"
      ]
    },
    {
      "id": "l3-dispatcher/skill-contract",
      "clauses": [
        "归属与依赖/变更关联"
      ],
      "status": "updated",
      "reason": "只登记技能、宿主及装配文件的关联，技能身份、生命周期、完成裁决正文保持。",
      "evidence": [
        "specs/implemented/inner/l3-skill-contract.spec.md",
        "doc/l3-dispatcher-planner/iteration/design-contract-change-sync.md"
      ]
    },
    {
      "id": "l3-dispatcher/tool-plane",
      "clauses": [
        "归属与依赖/变更关联"
      ],
      "status": "updated",
      "reason": "只追加工具控制面及catalog路径关联，默认集合、revision与线上行为正文保持。",
      "evidence": [
        "specs/implemented/inner/l3-tool-plane.spec.md",
        "doc/l3-dispatcher-planner/iteration/design-contract-change-sync.md"
      ]
    },
    {
      "id": "l3-dispatcher/tracking",
      "clauses": [
        "归属与依赖/变更关联"
      ],
      "status": "updated",
      "reason": "只登记跟踪、缓存、Elastic及原生消息路径，提案正文保持；未声明业务或外部消费通过。",
      "evidence": [
        "specs/proposed/inner/l3-tracking.spec.md",
        "doc/l3-dispatcher-planner/iteration/design-contract-change-sync.md"
      ]
    },
    {
      "id": "observability",
      "clauses": [
        "Inner contracts"
      ],
      "status": "unchanged",
      "reason": "日志叶只追加关联块，原父子登记、日志系统边界与身份保持，根无需文字修改。",
      "evidence": [
        "specs/implemented/observability.spec.md",
        "doc/l3-dispatcher-planner/iteration/design-contract-change-sync.md"
      ]
    },
    {
      "id": "observability/log",
      "clauses": [
        "归属与依赖/变更关联"
      ],
      "status": "updated",
      "reason": "只追加生产代码、日志部署和启动文件的关联，日志信封、事件及流水线正文保持。",
      "evidence": [
        "specs/implemented/inner/observability-log.spec.md",
        "doc/l3-dispatcher-planner/iteration/design-contract-change-sync.md"
      ]
    },
    {
      "id": "runtime",
      "clauses": [
        "Inner contracts"
      ],
      "status": "unchanged",
      "reason": "三个运行时提案叶仅追加关联数据，路径和状态未变，原提案根登记保持闭合。",
      "evidence": [
        "specs/proposed/runtime.spec.md",
        "doc/l3-dispatcher-planner/iteration/design-contract-change-sync.md"
      ]
    },
    {
      "id": "runtime/drone-remote-build",
      "clauses": [
        "归属与依赖/变更关联"
      ],
      "status": "updated",
      "reason": "只登记当前设备入口、构建及部署文件的关联，隔离与启停提案正文保持，未进行设备验证。",
      "evidence": [
        "specs/proposed/inner/drone-remote-build.spec.md",
        "doc/l3-dispatcher-planner/iteration/design-contract-change-sync.md"
      ]
    },
    {
      "id": "runtime/station-telemetry",
      "clauses": [
        "归属与依赖/变更关联"
      ],
      "status": "updated",
      "reason": "只登记遥测包与部署文件关联，原线上载荷及限流提案正文保持，未进行站端消费验证。",
      "evidence": [
        "specs/proposed/inner/station-telemetry.spec.md",
        "doc/l3-dispatcher-planner/iteration/design-contract-change-sync.md"
      ]
    },
    {
      "id": "runtime/unity-k3s-bringup",
      "clauses": [
        "归属与依赖/变更关联"
      ],
      "status": "updated",
      "reason": "只登记现有仿真入口、构建与部署路径，原提案配置和生命周期正文保持，未进行启动验证。",
      "evidence": [
        "specs/proposed/inner/unity-k3s-bringup.spec.md",
        "doc/l3-dispatcher-planner/iteration/design-contract-change-sync.md"
      ]
    },
    {
      "id": "topology",
      "clauses": [
        "Inner contracts"
      ],
      "status": "unchanged",
      "reason": "实体命名叶追加关联块但身份和路径未变，原根登记与系统命名边界无需修改。",
      "evidence": [
        "specs/implemented/topology.spec.md",
        "doc/l3-dispatcher-planner/iteration/design-contract-change-sync.md"
      ]
    },
    {
      "id": "topology/entity-naming",
      "clauses": [
        "归属与依赖/变更关联"
      ],
      "status": "updated",
      "reason": "关联数据覆盖门禁脚本；本轮沿用station-host实体和Invoked头，原脚本命名正文保持。",
      "evidence": [
        "specs/implemented/inner/entity-naming.spec.md",
        "doc/l3-dispatcher-planner/iteration/design-contract-change-sync.md"
      ]
    }
  ]
}
```

## 6. 删除清单

| 删除项 | 理由 |
|----|----|
| A1 仅以契约文件修改触发的限制 | 会漏掉只改实现的任务 |
| 将结构通过视为同步完成的暗示 | 两类检查必须明确区分 |

## 7. 实施步骤

### P0 — 规则与基线

- 范围：落盘本方案，捕获本轮治理文件范围的原始指纹；新增同步叶与强制入口。
- 不变量：原有未提交业务修改不进入本轮任务范围。
- 检查：文档结构检查；基线保存在忽略区。
- 回退：只移除本轮新增规则，不覆盖其他任务文件。

### P1 — 元数据与检查入口

- 范围：补齐叶关联、方案模板和门禁模式。
- 不变量：原业务条款保持，元数据只提供候选关联。
- 检查：候选完整、处置漏项失败；不执行被关联业务。
- 回退：同步撤回新模式及其规范声明，不留兼容入口。

### P2 — 本轮处置与交付

- 范围：依据实际差异填写本方案同步记录，记录文档检查证据。
- 不变量：候选不等于必须改业务要求；核对不变须说明原因。
- 检查：结构与同步模式通过，文档格式通过；业务内容排除。
- 回退：保持待同步状态并说明剩余问题，禁止虚报完成。

## 8. 验收标准

- `python3 specs/tools/station-host-spec-lint.py`：结构、关联元数据及依赖 ID 有效。
- `python3 specs/tools/station-host-spec-lint.py --list-impacts doc/l3-dispatcher-planner/iteration/design-contract-change-sync.md`：输出本轮候选，不当作同步通过。
- `python3 specs/tools/station-host-spec-lint.py --sync-plan doc/l3-dispatcher-planner/iteration/design-contract-change-sync.md`：候选逐项处理且证据有效。
- 使用忽略区文档样例确认漏项、pending、损坏基线和虚报更新均拒绝；不运行业务测试。
- 提交前隐私门禁不在本轮交付动作中触发；本轮不提交或推送。

## 9. 风险与对策

| 风险 | 对策 |
|----|----|
| 路径覆盖不完整 | 未映射路径必须补绑定，不能静默通过 |
| 关联过宽产生候选 | 用具体未变理由处置，不机械改动所有契约 |
| 外部或并发修改 | 基线区分原有修改；同范围并发变化仍报告，不猜测归属 |
| 记录被形式化填充 | 静态检查不替代人工判断，禁止宣称业务正确性通过 |

## 10. 修改点清单汇总

| 文件 | 动作 |
|----|----|
| `specs/README.md`、`AGENTS.md`、`.cursor/rules/spec-governance.mdc` | 强制实现任务触发同步机制 |
| `specs/implemented/development-workflow.spec.md` | 登记同步叶 |
| `specs/implemented/inner/spec-change-sync.spec.md` | 新增详细同步契约 |
| `specs/{implemented,proposed}/inner/*.spec.md` | 追加关联元数据 |
| `specs/tools/station-host-spec-lint.py` | 增加基线与同步模式 |
| `doc/l3-dispatcher-planner/iteration/_TEMPLATE.md` | 增加同步记录格式 |
| `specs/implemented/process/2026-10-14-contract-change-sync.md` | 记录治理选择 |

### 实施与检查记录

- 新增开发工作流同步叶并登记；17 份既有叶仅追加关联块，基线提交与当前正文对照确认原条款保持。
  加上新增同步叶，共 18 份叶具备路径绑定与依赖声明。依赖包含父根边界及文中已存在的契约引用。
- README、AGENTS、客户端引导已将实现及配置任务纳入强制核对；方案模板 §5 增加同步记录。
- 本轮在治理文件范围捕获 44 个起点路径；当时捕获模式尚未实现，由只读 Git 清单与指纹操作生成同格式基线。
  原基线保存在忽略区并固定 SHA-256，没有中途重置；原有业务工作区修改不在本轮范围。
- 首次候选模式发现 Git check-ignore 不支持 literal pathspec 全局选项，已限定该选项仅用于 ls-files。
  后续候选与同步模式均执行成功，不以首次失败当作通过。
- 实际任务差异为 26 个文件，识别 23 个候选契约，已在 §5 逐项记录 updated 或 unchanged 及条款和证据。
  空处置清单曾实际返回 1 并列出全部漏项；补齐后同步模式返回 0。
- 同步门禁关键样例 12 项通过：漏项、pending、虚报更新、损坏摘要、无效证据、无效条款被拒绝；
  基线捕获及禁止覆盖正确；识别新增、删除和重命名，排除原有未继续改变的文件；
  能反查未编辑的消费契约，不经登记父根展开全部同级叶；未绑定改动被拒绝。
  证据位于 `.artifacts/spec-sync/checks-1908272f/results.json`，全部样例仅检查文档与同步机制。
- 结构门禁读取 40 条记录，返回 0；同步模式对本方案返回 0；本轮文档与脚本的 diff 格式检查返回 0。
- 本轮不检查业务要求是否充分，不运行业务测试、构建或部署；没有提交、推送或安装钩子。
