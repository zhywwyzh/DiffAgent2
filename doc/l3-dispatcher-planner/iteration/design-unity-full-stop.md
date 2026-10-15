# 本机完整关闭与站端失败启动修复方案

> 摘要：按用户明确要求，make down 关闭本机固定 L4 服务，包括来自其他检出及失败启动的残留；修复 VLA 控制台入口缺失的本地环境。

## 0. 元信息

- 日期：2026-10-15
- 目标路径：`l3-dispatcher-planner/tools/station-host-sim.py`、Unity 操作说明及 runtime 契约
- 状态：代码已修改，当前残留服务已清理；完整启动及同步门禁未验收
- owner：station-host 运行时装配，契约仍为 proposed。
- 关联文档：`design-unity-make-lifecycle.md`、`design-unity-stop-idempotency.md`

## 1. 背景与动机

用户明确要求新版 make down 全关，不再要求手动到 Exploration 关闭站端。新 L4 的 VLA 虚拟环境脚本缺失，启动返回非零时原入口未登记已产生的服务。

## 2. 现状事实（问题清单）

- `tools/station-host-sim.py:696`：无站端登记直接跳过，漏掉部分启动和共享站端。
- `tools/station-host-sim.py:741`：成功执行 L4 make 后才写登记，启动失败留下未登记服务。
- `tools/station-host-sim.py:966`：完整 start 先启动仿真后检查站端依赖。
- `l4-agent/bringup/ground-station-native/run-agent-station-vla.sh:13`：需要 .venv/bin/agent-station-vla；实际日志为入口缺失、退出码 127。

## 3. 目标与约束

完整关闭包含本机 l4-app、bridge、visualizer、VLA 及固定退役站端单元，无论来自哪个检出或是否登记；操作之前仍检查任务停稳及安全释放站端连接。集群删除限本工作区，不杀未知进程、不关闭外部 Unity Editor。先检查必要可执行入口再启仿真，启动前登记。修复本地虚拟环境，不修改独立 L4 源码，不编译或运行测试/门禁。实际执行一次用户要求的清理操作，不启动飞行。

## 4. 方案决策

沿用 tools 与 bringup 架构，辅助函数 station_preflight、station_stop，不新增转接器或配置别名。station_stop 使用固定 systemd 服务集合，查询实际存在单元、停止并禁用、清理固定用户单元及相机 drop-in；检测未释放端口则报错，不以 kill 未知进程解决。
start 在业务栈前调用预检查，必需 python、copaw 和三项 sidecar 可执行入口。station.json 写在启动副作用前，错误保留供 down 清理。即使 marker 缺失，完整关闭仍停固定服务。
VLA 环境按已有 uv.lock 重新同步本地 copaw 包以生成正式控制台入口，不造手写启动包装。此环境修复不改变 L3 的 Python 3.8 镜像。

## 5. 迁移映射表

无登记跳过站端 → 固定本机站端完整清理；错误检出阻止关闭 → 仅启动保留归属检查，完整停止按用户授权关闭固定服务；启动成功才登记 → 启动之前登记。

### 配套契约同步记录

```contract-sync
{
  "baseline": ".artifacts/spec-sync/unity-full-stop-20261015.json",
  "baseline_sha256": "d4ffdfd7125193263c67296ff55905f9f6b84761c6e7cdb1a5d3313aed22fd00",
  "reviews": [
    {
      "id": "development-workflow",
      "clauses": [
        "边界"
      ],
      "status": "unchanged",
      "reason": "仅修改宿主机站端启停和预检查，不改变任务消息、技能、执行停止判据、日志载荷或领域归属。",
      "evidence": [
        "specs/implemented/development-workflow.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-full-stop.md"
      ]
    },
    {
      "id": "development-workflow/contract-sync",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "已捕获任务基线并记录候选处置；不修改同步规则，未获许可不运行门禁。",
      "evidence": [
        "specs/implemented/inner/spec-change-sync.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-full-stop.md"
      ]
    },
    {
      "id": "l3-dispatcher",
      "clauses": [
        "边界"
      ],
      "status": "unchanged",
      "reason": "仅修改宿主机站端启停和预检查，不改变任务消息、技能、执行停止判据、日志载荷或领域归属。",
      "evidence": [
        "specs/implemented/l3-dispatcher.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-full-stop.md"
      ]
    },
    {
      "id": "l3-dispatcher/core-boundary",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "仅修改宿主机站端启停和预检查，不改变任务消息、技能、执行停止判据、日志载荷或领域归属。",
      "evidence": [
        "specs/implemented/inner/l3-core-boundary.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-full-stop.md"
      ]
    },
    {
      "id": "l3-dispatcher/execution-seam",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "仅修改宿主机站端启停和预检查，不改变任务消息、技能、执行停止判据、日志载荷或领域归属。",
      "evidence": [
        "specs/implemented/inner/l3-execution-seam.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-full-stop.md"
      ]
    },
    {
      "id": "l3-dispatcher/flight-actions",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "仅修改宿主机站端启停和预检查，不改变任务消息、技能、执行停止判据、日志载荷或领域归属。",
      "evidence": [
        "specs/implemented/inner/flight-actions.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-full-stop.md"
      ]
    },
    {
      "id": "l3-dispatcher/l4-rpc",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "仅修改宿主机站端启停和预检查，不改变任务消息、技能、执行停止判据、日志载荷或领域归属。",
      "evidence": [
        "specs/implemented/inner/l3-l4-rpc.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-full-stop.md"
      ]
    },
    {
      "id": "l3-dispatcher/migration-protocol",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "仅修改宿主机站端启停和预检查，不改变任务消息、技能、执行停止判据、日志载荷或领域归属。",
      "evidence": [
        "specs/implemented/inner/l3-migration-protocol.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-full-stop.md"
      ]
    },
    {
      "id": "l3-dispatcher/package-layout",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "仅修改宿主机站端启停和预检查，不改变任务消息、技能、执行停止判据、日志载荷或领域归属。",
      "evidence": [
        "specs/implemented/inner/l3-package-layout.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-full-stop.md"
      ]
    },
    {
      "id": "l3-dispatcher/ros-adapter-boundary",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "仅修改宿主机站端启停和预检查，不改变任务消息、技能、执行停止判据、日志载荷或领域归属。",
      "evidence": [
        "specs/implemented/inner/l3-ros-adapter-boundary.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-full-stop.md"
      ]
    },
    {
      "id": "l3-dispatcher/scenegraph",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "仅修改宿主机站端启停和预检查，不改变任务消息、技能、执行停止判据、日志载荷或领域归属。",
      "evidence": [
        "specs/proposed/inner/l3-scenegraph.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-full-stop.md"
      ]
    },
    {
      "id": "l3-dispatcher/skill-contract",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "仅修改宿主机站端启停和预检查，不改变任务消息、技能、执行停止判据、日志载荷或领域归属。",
      "evidence": [
        "specs/implemented/inner/l3-skill-contract.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-full-stop.md"
      ]
    },
    {
      "id": "l3-dispatcher/tool-plane",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "仅修改宿主机站端启停和预检查，不改变任务消息、技能、执行停止判据、日志载荷或领域归属。",
      "evidence": [
        "specs/implemented/inner/l3-tool-plane.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-full-stop.md"
      ]
    },
    {
      "id": "l3-dispatcher/tracking",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "仅修改宿主机站端启停和预检查，不改变任务消息、技能、执行停止判据、日志载荷或领域归属。",
      "evidence": [
        "specs/proposed/inner/l3-tracking.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-full-stop.md"
      ]
    },
    {
      "id": "observability",
      "clauses": [
        "边界"
      ],
      "status": "unchanged",
      "reason": "仅修改宿主机站端启停和预检查，不改变任务消息、技能、执行停止判据、日志载荷或领域归属。",
      "evidence": [
        "specs/implemented/observability.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-full-stop.md"
      ]
    },
    {
      "id": "observability/log",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "仅修改宿主机站端启停和预检查，不改变任务消息、技能、执行停止判据、日志载荷或领域归属。",
      "evidence": [
        "specs/implemented/inner/observability-log.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-full-stop.md"
      ]
    },
    {
      "id": "runtime",
      "clauses": [
        "不变量"
      ],
      "status": "updated",
      "reason": "按用户明确要求，完整关闭包含本机固定 L4 服务，不再局限本工作区登记；集群资源仍按原 owner 删除。",
      "evidence": [
        "specs/proposed/runtime.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-full-stop.md"
      ]
    },
    {
      "id": "runtime/drone-remote-build",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "宿主仿真入口的完整站端关闭不扩展为远端设备关机或删除；设备侧构建、健康及停止要求保持。",
      "evidence": [
        "specs/proposed/inner/drone-remote-build.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-full-stop.md"
      ]
    },
    {
      "id": "runtime/station-telemetry",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "只管理站端服务生命周期，不修改遥测消息、来源、限流、实例身份和生产者。",
      "evidence": [
        "specs/proposed/inner/station-telemetry.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-full-stop.md"
      ]
    },
    {
      "id": "runtime/unity-k3s-bringup",
      "clauses": [
        "失败、取消与资源生命周期"
      ],
      "status": "updated",
      "reason": "同步完整站端关闭、失败启动提前登记及先检查依赖再启动仿真的要求，保留安全释放租约和动态停稳。",
      "evidence": [
        "specs/proposed/inner/unity-k3s-bringup.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-full-stop.md"
      ]
    },
    {
      "id": "topology",
      "clauses": [
        "边界"
      ],
      "status": "unchanged",
      "reason": "仅修改宿主机站端启停和预检查，不改变任务消息、技能、执行停止判据、日志载荷或领域归属。",
      "evidence": [
        "specs/implemented/topology.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-full-stop.md"
      ]
    },
    {
      "id": "topology/entity-naming",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "仅修改宿主机站端启停和预检查，不改变任务消息、技能、执行停止判据、日志载荷或领域归属。",
      "evidence": [
        "specs/implemented/inner/entity-naming.spec.md",
        "l3-dispatcher-planner/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-unity-full-stop.md"
      ]
    }
  ]
}
```

## 6. 删除清单

删除无登记停止跳过分支、停止路径的检出限制以及启动后才登记的顺序。保留安全停稳、租约失败和未知进程不强杀约束。

## 7. 实施步骤

P0 建立基线、落盘方案；P1 先修订 runtime 根及 Unity 叶；P2 完整站端停止和启动预检查；P3 执行当前残留栈的完整关闭，再按锁文件修复本地 L4 安装。若安全关闭失败保留资源并报告，不绕过。回退仅撤销本轮改动，不覆盖既有代码。

## 8. 验收标准

未获测试或门禁许可，不运行。记录实际清理与依赖修复命令及结果，不当作业务验收；完整启动和模型能力待用户后续执行。后续获准覆盖无登记、跨检出、部分失败、缺可执行入口、活动任务拒绝和端口残留。

## 9. 风险与对策

完整关闭会影响本机共享站端，这是用户本轮明确授权的行为变更；有连接时先安全释放，不能静默丢弃正在执行的任务。缺 DBus 或无法查询服务应明确失败。虚拟环境更新使用 frozen 锁文件，不升级到未锁依赖。

## 10. 修改点清单汇总

- tools/station-host-sim.py：完整关闭、提前预检查、失败启动登记。
- bringup/k3s/unity/README.md：全关语义与依赖错误说明。
- runtime 根及 Unity 叶：同步用户授权的本机共享服务关闭边界。
- 被忽略的 L4 虚拟环境：按锁文件修复正式入口。


### 实际执行记录

已执行用户要求的 make down，退出码 0：本工作区仿真资源停止，本机固定 L4 四服务停止、禁用并清理用户单元及相机 drop-in。namespace、编译产物及外部 Unity 保留。
VLA 失败直接原因为正式控制台脚本缺失，服务退出码 127。执行 uv sync --frozen --no-extra channels --project l4-agent --reinstall-package copaw 成功，安装正式 agent-station-vla 入口并补齐锁定依赖；未修改独立 L4 源码。
读取新生成入口确认指向 copaw.station_sidecar.vla.server:main。未执行服务重启、完整启动、测试套件、结构门禁或同步门禁，不宣称 VLA 运行健康或配套契约门禁通过。
