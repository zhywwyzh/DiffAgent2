# 工作区角色目录与部署归属迁移方案

> 摘要：按用户采纳的角色结构迁移项目与编排，严格同步根 Makefile、契约关联、文档导航及源码挂载。

## 0. 元信息

- 日期：2026-10-15
- 范围：根目录、项目目录、deployment、specs、doc、AGENTS.md 与 CODEBUDDY.md。
- 状态：目录与配套文件已迁移，静态同步门禁待许可执行
- owner：工作区布局归 development-workflow/workspace-layout，运行装配归 runtime 叶。
- 关联文档：`design-unity-make-lifecycle.md`、`design-unity-full-stop.md`。

## 1. 背景与动机

当前机端、站端及仿真检出平铺；全栈管理嵌在 L3 内，根目录定位依赖 L3.parent。用户明确采纳角色分组并要求 Makefile 与契约严格同步。

## 2. 现状事实（问题清单）

- `Makefile:8`：根入口绑定 L3 内部全栈工具。
- `l3-dispatcher-planner/tools/station-host-sim.py:25`：根目录被假定为 L3 父目录。
- `l3-dispatcher-planner/tools/station-host-drone.py:24`：源码冻结与设备 worker 位于算法项目。
- `.gitignore:3`：按顶层 l 前缀忽略独立检出，迁移后必须改为明确新位置。
- `specs/implemented/inner/l3-package-layout.spec.md`：规范 dispatcher 内部结构，不拥有仓库顶层布局。

## 3. 目标与约束

机端 L3 内置子树移到 drone_projects，站端 L4 独立检出移到 station_projects，L2 仿真独立检出移到 simulation_projects。全栈工具、k3s 清单及装配制品归 deployment。保留独立仓库、既有 Git 历史和本地配置，不提交外部源码，不创建软链接或旧路径包装。spec 仍只放根 specs；历史决策正文路径不伪造为新事实，仅修导航。
只读确认当前无业务 Deployment 和活动 L4 后迁移，不主动部署或飞行。已异步请求静态检查许可；未获明确答复前不运行门禁或验证。

## 4. 方案决策

目标结构：

```
drone_projects/l3-dispatcher-planner/
station_projects/l4-agent/
simulation_projects/l2-simulator-amd64/
deployment/tools/
deployment/k3s/{unity,real}/
deployment/.artifacts/
specs/
doc/l3-dispatcher-planner/
Makefile
```

实际目录使用 ASCII drone_projects；文档 workspace 名保留 l3-dispatcher-planner。
主机入口继续使用 station-host-/drone-host- 前缀；项目构建脚本保留 tools/build_ego.sh。
容器 /source/l3 与 /work/l3 保持，部署文件单独挂载 /source/deployment。设备源码冻结保持仓库相对角色路径，设备挂载对应子树；禁止继续把部署清单打包为 L3 bringup。
根目录由 deployment 的固定层级解析，owner 仍取原仓库根哈希，保留 namespace 身份。默认检出路径更新；本地明确覆盖若指向被迁移目录同步更新，外部覆盖不猜改。
缓存随 deployment 归集，旧构建签名因真实主机路径变化需重新 prepare，保留缓存及日志。迁移 L4 后使用既有锁文件重建本地虚拟环境，旧环境留在忽略区，不迁入父仓库。

## 5. 迁移映射表

- 根 l3-dispatcher-planner → drone_projects/l3-dispatcher-planner。
- 根 l4-agent → station_projects/l4-agent（独立检出）。
- 根 l2-simulator-amd64 → simulation_projects/l2-simulator-amd64（独立检出）。
- L3 tools/{station-host-sim,station-host-drone,drone-host-runtime}.py → deployment/tools/。
- L3 bringup/k3s → deployment/k3s；L3 .artifacts/{k3s-unity,drone} → deployment/.artifacts/。

### 配套契约同步记录

```contract-sync
{
  "baseline": ".artifacts/spec-sync/workspace-role-layout-20261015.json",
  "baseline_sha256": "0370fe29f8ad9825b7f08f6c31d096d81444cd750ee9d9bbcd18db020f1c3d93",
  "reviews": [
    {
      "id": "development-workflow",
      "clauses": [
        "Inner contracts"
      ],
      "status": "updated",
      "reason": "登记已采纳的工作区角色布局叶契约，保持源码和版本 owner 纪律。",
      "evidence": [
        "specs/implemented/development-workflow.spec.md",
        "Makefile",
        "deployment/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-workspace-role-layout.md"
      ]
    },
    {
      "id": "topology/entity-naming",
      "clauses": [
        "行为规则",
        "归属与依赖"
      ],
      "status": "updated",
      "reason": "将全栈工具和容器脚本的绑定同步至 deployment，执行实体词汇及前缀保持。",
      "evidence": [
        "specs/implemented/inner/entity-naming.spec.md",
        "Makefile",
        "deployment/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-workspace-role-layout.md"
      ]
    },
    {
      "id": "l3-dispatcher/flight-actions",
      "clauses": [
        "归属与依赖"
      ],
      "status": "updated",
      "reason": "实现绑定及当前源码引用已随角色目录迁移同步，契约身份、业务条款和生命周期保持。",
      "evidence": [
        "specs/implemented/inner/flight-actions.spec.md",
        "Makefile",
        "deployment/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-workspace-role-layout.md"
      ]
    },
    {
      "id": "development-workflow/l3-coding-style",
      "clauses": [
        "归属与依赖"
      ],
      "status": "updated",
      "reason": "实现绑定及当前源码引用已随角色目录迁移同步，契约身份、业务条款和生命周期保持。",
      "evidence": [
        "specs/implemented/inner/l3-coding-style.spec.md",
        "Makefile",
        "deployment/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-workspace-role-layout.md"
      ]
    },
    {
      "id": "l3-dispatcher/core-boundary",
      "clauses": [
        "归属与依赖"
      ],
      "status": "updated",
      "reason": "实现绑定及当前源码引用已随角色目录迁移同步，契约身份、业务条款和生命周期保持。",
      "evidence": [
        "specs/implemented/inner/l3-core-boundary.spec.md",
        "Makefile",
        "deployment/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-workspace-role-layout.md"
      ]
    },
    {
      "id": "l3-dispatcher/execution-seam",
      "clauses": [
        "归属与依赖"
      ],
      "status": "updated",
      "reason": "实现绑定及当前源码引用已随角色目录迁移同步，契约身份、业务条款和生命周期保持。",
      "evidence": [
        "specs/implemented/inner/l3-execution-seam.spec.md",
        "Makefile",
        "deployment/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-workspace-role-layout.md"
      ]
    },
    {
      "id": "l3-dispatcher/l4-rpc",
      "clauses": [
        "归属与依赖"
      ],
      "status": "updated",
      "reason": "实现绑定及当前源码引用已随角色目录迁移同步，契约身份、业务条款和生命周期保持。",
      "evidence": [
        "specs/implemented/inner/l3-l4-rpc.spec.md",
        "Makefile",
        "deployment/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-workspace-role-layout.md"
      ]
    },
    {
      "id": "l3-dispatcher/migration-protocol",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "实现路径、职责及参数语义经迁移核对保持，本轮目录分组不改变本契约的行为要求。",
      "evidence": [
        "specs/implemented/inner/l3-migration-protocol.spec.md",
        "Makefile",
        "deployment/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-workspace-role-layout.md"
      ]
    },
    {
      "id": "l3-dispatcher/package-layout",
      "clauses": [
        "归属与依赖"
      ],
      "status": "updated",
      "reason": "实现绑定及当前源码引用已随角色目录迁移同步，契约身份、业务条款和生命周期保持。",
      "evidence": [
        "specs/implemented/inner/l3-package-layout.spec.md",
        "Makefile",
        "deployment/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-workspace-role-layout.md"
      ]
    },
    {
      "id": "l3-dispatcher/ros-adapter-boundary",
      "clauses": [
        "归属与依赖"
      ],
      "status": "updated",
      "reason": "实现绑定及当前源码引用已随角色目录迁移同步，契约身份、业务条款和生命周期保持。",
      "evidence": [
        "specs/implemented/inner/l3-ros-adapter-boundary.spec.md",
        "Makefile",
        "deployment/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-workspace-role-layout.md"
      ]
    },
    {
      "id": "l3-dispatcher/skill-contract",
      "clauses": [
        "归属与依赖"
      ],
      "status": "updated",
      "reason": "实现绑定及当前源码引用已随角色目录迁移同步，契约身份、业务条款和生命周期保持。",
      "evidence": [
        "specs/implemented/inner/l3-skill-contract.spec.md",
        "Makefile",
        "deployment/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-workspace-role-layout.md"
      ]
    },
    {
      "id": "l3-dispatcher/tool-plane",
      "clauses": [
        "归属与依赖"
      ],
      "status": "updated",
      "reason": "实现绑定及当前源码引用已随角色目录迁移同步，契约身份、业务条款和生命周期保持。",
      "evidence": [
        "specs/implemented/inner/l3-tool-plane.spec.md",
        "Makefile",
        "deployment/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-workspace-role-layout.md"
      ]
    },
    {
      "id": "observability/log",
      "clauses": [
        "归属与依赖"
      ],
      "status": "updated",
      "reason": "实现绑定及当前源码引用已随角色目录迁移同步，契约身份、业务条款和生命周期保持。",
      "evidence": [
        "specs/implemented/inner/observability-log.spec.md",
        "Makefile",
        "deployment/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-workspace-role-layout.md"
      ]
    },
    {
      "id": "development-workflow/contract-sync",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "迁移前捕获覆盖旧新路径的基线，记录全部候选处置；同步规则未更改，检查许可仍按 AGENTS。",
      "evidence": [
        "specs/implemented/inner/spec-change-sync.spec.md",
        "Makefile",
        "deployment/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-workspace-role-layout.md"
      ]
    },
    {
      "id": "l3-dispatcher",
      "clauses": [
        "边界"
      ],
      "status": "unchanged",
      "reason": "实现路径、职责及参数语义经迁移核对保持，本轮目录分组不改变本契约的行为要求。",
      "evidence": [
        "specs/implemented/l3-dispatcher.spec.md",
        "Makefile",
        "deployment/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-workspace-role-layout.md"
      ]
    },
    {
      "id": "observability",
      "clauses": [
        "边界"
      ],
      "status": "unchanged",
      "reason": "实现路径、职责及参数语义经迁移核对保持，本轮目录分组不改变本契约的行为要求。",
      "evidence": [
        "specs/implemented/observability.spec.md",
        "Makefile",
        "deployment/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-workspace-role-layout.md"
      ]
    },
    {
      "id": "topology",
      "clauses": [
        "边界"
      ],
      "status": "unchanged",
      "reason": "实现路径、职责及参数语义经迁移核对保持，本轮目录分组不改变本契约的行为要求。",
      "evidence": [
        "specs/implemented/topology.spec.md",
        "Makefile",
        "deployment/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-workspace-role-layout.md"
      ]
    },
    {
      "id": "runtime/drone-remote-build",
      "clauses": [
        "术语与身份",
        "归属与依赖"
      ],
      "status": "updated",
      "reason": "已同步部署入口与设备发布清单的角色路径，以及独立 deployment 源码挂载；未连接或变更设备。",
      "evidence": [
        "specs/proposed/inner/drone-remote-build.spec.md",
        "Makefile",
        "deployment/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-workspace-role-layout.md"
      ]
    },
    {
      "id": "l3-dispatcher/scenegraph",
      "clauses": [
        "归属与依赖"
      ],
      "status": "updated",
      "reason": "实现绑定及当前源码引用已随角色目录迁移同步，契约身份、业务条款和生命周期保持。",
      "evidence": [
        "specs/proposed/inner/l3-scenegraph.spec.md",
        "Makefile",
        "deployment/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-workspace-role-layout.md"
      ]
    },
    {
      "id": "l3-dispatcher/tracking",
      "clauses": [
        "归属与依赖"
      ],
      "status": "updated",
      "reason": "实现绑定及当前源码引用已随角色目录迁移同步，契约身份、业务条款和生命周期保持。",
      "evidence": [
        "specs/proposed/inner/l3-tracking.spec.md",
        "Makefile",
        "deployment/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-workspace-role-layout.md"
      ]
    },
    {
      "id": "runtime/station-telemetry",
      "clauses": [
        "归属与依赖"
      ],
      "status": "updated",
      "reason": "实现绑定及当前源码引用已随角色目录迁移同步，契约身份、业务条款和生命周期保持。",
      "evidence": [
        "specs/proposed/inner/station-telemetry.spec.md",
        "Makefile",
        "deployment/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-workspace-role-layout.md"
      ]
    },
    {
      "id": "runtime/unity-k3s-bringup",
      "clauses": [
        "输入、输出与配置",
        "归属与依赖"
      ],
      "status": "updated",
      "reason": "已同步新入口、角色项目路径、部署探针挂载及制品归属；原安全启停和任务协议保持。",
      "evidence": [
        "specs/proposed/inner/unity-k3s-bringup.spec.md",
        "Makefile",
        "deployment/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-workspace-role-layout.md"
      ]
    },
    {
      "id": "runtime",
      "clauses": [
        "边界"
      ],
      "status": "unchanged",
      "reason": "实现路径、职责及参数语义经迁移核对保持，本轮目录分组不改变本契约的行为要求。",
      "evidence": [
        "specs/proposed/runtime.spec.md",
        "Makefile",
        "deployment/tools/station-host-sim.py",
        "doc/l3-dispatcher-planner/iteration/design-workspace-role-layout.md"
      ]
    },
    {
      "id": "development-workflow/workspace-layout",
      "clauses": [
        "输入、输出与配置",
        "行为规则",
        "归属与依赖"
      ],
      "status": "updated",
      "reason": "用户已明确采纳角色目录及部署分离；新增唯一布局契约并完成父根登记，不复制运行行为要求。",
      "evidence": [
        "specs/implemented/inner/workspace-layout.spec.md",
        "specs/implemented/development-workflow.spec.md",
        "specs/implemented/architecture/2026-10-15-workspace-role-layout.md",
        "Makefile"
      ]
    }
  ]
}
```

## 6. 删除清单

删除旧顶层项目路径及旧 L3 编排入口，不留兼容链接；替换全部当前生效路径绑定。保留冻结历史决策的原始代码路径，并记录迁移映射；历史导航链接指向现有文件。

## 7. 实施步骤

P0 读取契约、捕获覆盖移动两端的基线、落盘方案。P1 新建已采纳工作区布局叶及结构决策，同步父根和运行时叶。P2 更新忽略规则并物理移动项目、部署及制品。P3 同步 Makefile、脚本根定位、容器挂载、设备源码冻结和本地配置。P4 更新 Markdown 链接、当前文档引用、代码图谱导航，修复 L4 本地环境。P5 获准后静态检查与契约同步检查，缺陷同轮修复。
回退仅逆向本轮目录与路径映射，保留本地配置和外部仓库历史，不回滚并发源码。

## 8. 验收标准

待静态许可：Makefile 干运行、Python 语法、路径与 Markdown 导航、契约结构及 --sync-plan 全部通过。独立检出保持被忽略，L3 与部署纳入父仓库。检查不得触发 SSH、编译、服务启动或飞行。
未获业务许可不编译或验收；报告实际静态结果和剩余运行条件，不能以文件已改宣称严格同步通过。

## 9. 风险与对策

移动使 catkin、虚拟环境和挂载的绝对路径过期：保留制品但要求重新 prepare，按锁文件重新生成 L4 环境。运行身份哈希必须继续取同一根目录。旧冻结方案中的源码路径保留历史语义，通过导航和新映射说明迁移。

## 10. 修改点清单汇总

角色项目目录、deployment、Makefile、.gitignore、AGENTS.md、CODEBUDDY.md、根 README、当前契约实现绑定、运行时文档和源码图谱。原任务基线保持只读，最终逐项核对处置。


### 实际迁移记录

已物理迁移 L3、L4、仿真 L2、三项全栈工具、k3s 清单及对应本地制品。根 Makefile 与主机根定位已更新，设备冻结清单按新职责路径打包并分别挂载 L3 和 deployment。
旧角色路径未保留软链接或包装入口。独立 L2/L4 的 Git 目录随检出移动，不提交或更改远端。
本地 L4 原虚拟环境已保存到 deployment 的忽略区，并执行 uv sync --frozen --no-extra channels --project station_projects/l4-agent 重新创建正式环境，退出码 0。未修改 L4 源码。
当前 Markdown 导航与契约绑定已维护；冻结历史决策正文中的源码路径保留当时事实。离线源码图谱已按新路径重新生成 24 个章节、83 组摘录。
迁移前只读查询确认无本工作区 Deployment，L4 inactive。未运行业务测试、编译、SSH 或服务启动；静态检查等待用户明确许可，不宣称同步门禁已通过。

### IDE 仓库发现补修

目录迁移遗漏了 IDE 仓库发现与 CMake 路径。只读调查确认 L2/L4 的 Git 元数据完整，L3 仍属于父仓库；Git 插件默认扫描深度为一层，角色目录中的独立检出位于第二层。
补修独立记录于 [IDE Git 发现修复方案](design-workspace-git-discovery.md)，使用自己的修改前基线，不覆盖原迁移基线。共享设置显式列出独立检出新路径并修复 CMake 定位；仅放行可移植设置文件，保持独立仓库源码及元数据被父仓库忽略。IDE 界面复查及同步门禁未运行。
