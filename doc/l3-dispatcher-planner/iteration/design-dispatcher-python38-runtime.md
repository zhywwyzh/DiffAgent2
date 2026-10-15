# dispatcher Python 3.8 运行初始化兼容方案

> 摘要：直接替换 create_flight_runtime 中的 Python 3.9 字符串 API，保持现有退休参数拒绝语义。

## 0. 元信息

- 日期：2026-10-15
- 目标路径：`l3-dispatcher-planner/ros_packages/dispatcher/dispatcher_node.py`
- owner：dispatcher 装配根；记录类型为实施方案，不新增业务契约。
- 状态：代码已修改，构建与运行验证及同步门禁待许可
- 关联文档：`design-unity-python38-build.md`

## 1. 背景与动机

用户启动 L3 后 dispatcher 在运行初始化中因 str.removesuffix 不存在退出。现有镜像使用 Python 3.8；依赖导入不执行运行初始化，因此编译准备未覆盖此异常。

## 2. 现状事实（问题清单）

- `l3-dispatcher-planner/ros_packages/dispatcher/dispatcher_node.py:135`：对两个明确带 _s 后缀的配置字段调用 removesuffix，要求 Python 3.9。
- `l3-dispatcher-planner/bringup/k3s/unity/runtime_probe_ros.py:159`：导入入口不执行 main，不能作为运行初始化已通过的证据。

## 3. 目标与约束

使用 Python 3.8 支持的切片表达相同字符串操作；不改变参数树、错误信息、默认值、镜像或起降逻辑。不引入转接器。仅修改源代码，不执行构建、测试、门禁或运行验收，不操作现有服务。

## 4. 方案决策

保留现有文件与目录架构、create_flight_runtime 和 old_name 命名。field.name 属于 state_timeout_s、action_timeout_s 时用 [:-2] 删除已知后缀，其余字段原样保留。不使用 rstrip，避免错误移除字符集合；不新增兼容函数。

## 5. 迁移映射表

field.name.removesuffix("_s") → field.name[:-2]，适用分支集合不变，直接替换。

### 配套契约同步记录

```contract-sync
{
  "baseline": ".artifacts/spec-sync/dispatcher-python38-runtime-20261015.json",
  "baseline_sha256": "4d3c78a8d6e829d77860fb38694f2c5e74475acb86414f58e2b1f4242848b3bb",
  "reviews": [
    {
      "id": "development-workflow",
      "clauses": [
        "边界"
      ],
      "status": "unchanged",
      "reason": "仅修正装配根字符串处理的解释器兼容性，不改变本契约的领域职责、接口、状态机或资源生命周期。",
      "evidence": [
        "specs/implemented/development-workflow.spec.md",
        "l3-dispatcher-planner/ros_packages/dispatcher/dispatcher_node.py",
        "doc/l3-dispatcher-planner/iteration/design-dispatcher-python38-runtime.md"
      ]
    },
    {
      "id": "development-workflow/contract-sync",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "按当前规范捕获修改前基线并记录候选处置，不改变同步规则；同步门禁未获授权执行。",
      "evidence": [
        "specs/implemented/inner/spec-change-sync.spec.md",
        "l3-dispatcher-planner/ros_packages/dispatcher/dispatcher_node.py",
        "doc/l3-dispatcher-planner/iteration/design-dispatcher-python38-runtime.md"
      ]
    },
    {
      "id": "l3-dispatcher",
      "clauses": [
        "边界"
      ],
      "status": "unchanged",
      "reason": "仅修正装配根字符串处理的解释器兼容性，不改变本契约的领域职责、接口、状态机或资源生命周期。",
      "evidence": [
        "specs/implemented/l3-dispatcher.spec.md",
        "l3-dispatcher-planner/ros_packages/dispatcher/dispatcher_node.py",
        "doc/l3-dispatcher-planner/iteration/design-dispatcher-python38-runtime.md"
      ]
    },
    {
      "id": "l3-dispatcher/core-boundary",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "修改位于装配根 create_flight_runtime，不改变 core 六态、任务队列、领域禁令或方法白名单。",
      "evidence": [
        "specs/implemented/inner/l3-core-boundary.spec.md",
        "l3-dispatcher-planner/ros_packages/dispatcher/dispatcher_node.py",
        "doc/l3-dispatcher-planner/iteration/design-dispatcher-python38-runtime.md"
      ]
    },
    {
      "id": "l3-dispatcher/execution-seam",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "保留旧 flight 参数拒绝及唯一 planner_execution 参数树，仅以切片等价计算两个退休参数名，不改变字段或默认值。",
      "evidence": [
        "specs/implemented/inner/l3-execution-seam.spec.md",
        "l3-dispatcher-planner/ros_packages/dispatcher/dispatcher_node.py",
        "doc/l3-dispatcher-planner/iteration/design-dispatcher-python38-runtime.md"
      ]
    },
    {
      "id": "l3-dispatcher/flight-actions",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "仅修正装配根字符串处理的解释器兼容性，不改变本契约的领域职责、接口、状态机或资源生命周期。",
      "evidence": [
        "specs/implemented/inner/flight-actions.spec.md",
        "l3-dispatcher-planner/ros_packages/dispatcher/dispatcher_node.py",
        "doc/l3-dispatcher-planner/iteration/design-dispatcher-python38-runtime.md"
      ]
    },
    {
      "id": "l3-dispatcher/l4-rpc",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "仅修正装配根字符串处理的解释器兼容性，不改变本契约的领域职责、接口、状态机或资源生命周期。",
      "evidence": [
        "specs/implemented/inner/l3-l4-rpc.spec.md",
        "l3-dispatcher-planner/ros_packages/dispatcher/dispatcher_node.py",
        "doc/l3-dispatcher-planner/iteration/design-dispatcher-python38-runtime.md"
      ]
    },
    {
      "id": "l3-dispatcher/migration-protocol",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "在新版装配根直接替换不兼容 API，不引入转接器或旧接口别名，也不迁入旧领域行为。",
      "evidence": [
        "specs/implemented/inner/l3-migration-protocol.spec.md",
        "l3-dispatcher-planner/ros_packages/dispatcher/dispatcher_node.py",
        "doc/l3-dispatcher-planner/iteration/design-dispatcher-python38-runtime.md"
      ]
    },
    {
      "id": "l3-dispatcher/package-layout",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "仅修正装配根字符串处理的解释器兼容性，不改变本契约的领域职责、接口、状态机或资源生命周期。",
      "evidence": [
        "specs/implemented/inner/l3-package-layout.spec.md",
        "l3-dispatcher-planner/ros_packages/dispatcher/dispatcher_node.py",
        "doc/l3-dispatcher-planner/iteration/design-dispatcher-python38-runtime.md"
      ]
    },
    {
      "id": "l3-dispatcher/ros-adapter-boundary",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "仅修正装配根字符串处理的解释器兼容性，不改变本契约的领域职责、接口、状态机或资源生命周期。",
      "evidence": [
        "specs/implemented/inner/l3-ros-adapter-boundary.spec.md",
        "l3-dispatcher-planner/ros_packages/dispatcher/dispatcher_node.py",
        "doc/l3-dispatcher-planner/iteration/design-dispatcher-python38-runtime.md"
      ]
    },
    {
      "id": "l3-dispatcher/scenegraph",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "仅修正装配根字符串处理的解释器兼容性，不改变本契约的领域职责、接口、状态机或资源生命周期。",
      "evidence": [
        "specs/proposed/inner/l3-scenegraph.spec.md",
        "l3-dispatcher-planner/ros_packages/dispatcher/dispatcher_node.py",
        "doc/l3-dispatcher-planner/iteration/design-dispatcher-python38-runtime.md"
      ]
    },
    {
      "id": "l3-dispatcher/skill-contract",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "仅修正装配根字符串处理的解释器兼容性，不改变本契约的领域职责、接口、状态机或资源生命周期。",
      "evidence": [
        "specs/implemented/inner/l3-skill-contract.spec.md",
        "l3-dispatcher-planner/ros_packages/dispatcher/dispatcher_node.py",
        "doc/l3-dispatcher-planner/iteration/design-dispatcher-python38-runtime.md"
      ]
    },
    {
      "id": "l3-dispatcher/tool-plane",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "仅修正装配根字符串处理的解释器兼容性，不改变本契约的领域职责、接口、状态机或资源生命周期。",
      "evidence": [
        "specs/implemented/inner/l3-tool-plane.spec.md",
        "l3-dispatcher-planner/ros_packages/dispatcher/dispatcher_node.py",
        "doc/l3-dispatcher-planner/iteration/design-dispatcher-python38-runtime.md"
      ]
    },
    {
      "id": "l3-dispatcher/tracking",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "仅修正装配根字符串处理的解释器兼容性，不改变本契约的领域职责、接口、状态机或资源生命周期。",
      "evidence": [
        "specs/proposed/inner/l3-tracking.spec.md",
        "l3-dispatcher-planner/ros_packages/dispatcher/dispatcher_node.py",
        "doc/l3-dispatcher-planner/iteration/design-dispatcher-python38-runtime.md"
      ]
    },
    {
      "id": "observability",
      "clauses": [
        "边界"
      ],
      "status": "unchanged",
      "reason": "仅修正装配根字符串处理的解释器兼容性，不改变本契约的领域职责、接口、状态机或资源生命周期。",
      "evidence": [
        "specs/implemented/observability.spec.md",
        "l3-dispatcher-planner/ros_packages/dispatcher/dispatcher_node.py",
        "doc/l3-dispatcher-planner/iteration/design-dispatcher-python38-runtime.md"
      ]
    },
    {
      "id": "observability/log",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "参数错误检查的名称和异常文本保持，字符串切片不改变结构化日志或失败事件语义。",
      "evidence": [
        "specs/implemented/inner/observability-log.spec.md",
        "l3-dispatcher-planner/ros_packages/dispatcher/dispatcher_node.py",
        "doc/l3-dispatcher-planner/iteration/design-dispatcher-python38-runtime.md"
      ]
    }
  ]
}
```

## 6. 删除清单

删除本处 removesuffix 调用，不保留旧 API 或兼容包装。

## 7. 实施步骤

P0 读取契约并捕获基线、落盘方案；P1 单处等价替换；P2 阅读实际差异并记录检查边界。回退仅恢复本处表达式，不覆盖其它未提交修改。

## 8. 验收标准

按 AGENTS.md 统一声明，本轮未获测试或门禁许可，不执行。后续获准后在 Python 3.8 核对两个退休参数名及普通字段、装配初始化和旧键拒绝行为；同步门禁仍待检查。

## 9. 风险与对策

切片依赖固定后缀：只在两个明确字段名的原有分支内使用。此修复仅覆盖已定位 API，不宣称整个初始化或启动链均已验收。

## 10. 修改点清单汇总

- dispatcher_node.py：单处 removesuffix 改为切片，保留错误检查。
- 本方案：修改前基线、配套契约处置和检查边界。

本轮实际执行基线捕获及源码差异阅读，代码仅替换一处字符串操作。未运行测试、构建、同步门禁或服务启停。
