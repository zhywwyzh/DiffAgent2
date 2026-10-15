# 角色目录迁移后的 IDE Git 发现修复方案

> 摘要：补齐 IDE 对角色目录下独立检出的发现配置，修正旧 CMake 源码定位；保留现有 Git 元数据、历史、远端和版本归属。

## 0. 元信息

- 日期：2026-10-15。
- 目标：`.vscode/settings.json`、`.gitignore`、工作区布局契约及本轮实施记录。
- 状态：in-progress；门禁与 IDE 界面验收未获许可，未运行。
- 关联：[角色目录迁移方案](design-workspace-role-layout.md)。

## 1. 背景与动机

用户报告迁移目录后 IDE 中 L2/L3/L4 的 Git 功能不可见。只读调查确认 L2/L4 的独立 Git 仓库可用，L3 仍由父仓库跟踪；修复重点为迁移遗漏的 IDE 路径。

## 2. 现状事实（问题清单）

- `.vscode/settings.json:2`：CMake 指向迁移前的 L3 目录，且未登记新的独立仓库路径。
- `.gitignore:43`：工作区设置整体忽略，无法随迁移交付可移植的发现配置。
- `specs/implemented/inner/workspace-layout.spec.md:23`：迁移同步项遗漏 IDE 路径。
- 本机 Git 插件配置声明 `git.repositoryScanMaxDepth` 缺省为 1；独立仓库迁移后处于第二层。插件支持 `git.scanRepositories` 的仓库相对路径。

## 3. 目标与约束

让打开编排根目录的 IDE 显式发现 L2/L4；L3 的修改继续归父仓库。仅变更当前工作区设置，不更改全局 IDE 偏好，不初始化新 Git 仓库，不变更分支、远端、历史和暂存区，不恢复旧路径转接口。

## 4. 方案决策

保留现有角色目录。工作区设置使用 `git.autoRepositoryDetection=true`，通过 `git.scanRepositories` 显式列出两个独立检出，避免依赖扫描深度。CMake 源码路径改用 `${workspaceFolder}/drone_projects/l3-dispatcher-planner/ros_packages/dispatcher`。仅允许 `.vscode/settings.json` 纳入父仓库，其余 IDE 本地文件继续忽略；设置内不得带机器路径。

## 5. 迁移映射与配套契约

旧顶层独立检出发现路径改为 `simulation_projects/l2-simulator-amd64`、`station_projects/l4-agent`；旧 CMake 源码定位改为角色目录相对定位。原目录迁移基线保持不变，本修复单独捕获修改前基线。

```contract-sync
{
  "baseline": ".artifacts/spec-sync/workspace-git-discovery-20261015.json",
  "baseline_sha256": "d2752db2147fda3fdbf620e9806db3104086eb70c6837782211e337b3d221f8b",
  "reviews": [
    {
      "id": "development-workflow",
      "clauses": [
        "Inner contracts"
      ],
      "status": "unchanged",
      "reason": "本轮只补充 IDE 仓库发现与 CMake 源码定位，以及相应实施记录；未改变本契约的源码实现、运行接口、行为要求或父子登记。",
      "evidence": [
        "specs/implemented/inner/workspace-layout.spec.md",
        ".vscode/settings.json",
        "doc/l3-dispatcher-planner/iteration/design-workspace-git-discovery.md"
      ]
    },
    {
      "id": "topology/entity-naming",
      "clauses": [
        "行为规则",
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "本轮只补充 IDE 仓库发现与 CMake 源码定位，以及相应实施记录；未改变本契约的源码实现、运行接口、行为要求或父子登记。",
      "evidence": [
        "specs/implemented/inner/workspace-layout.spec.md",
        ".vscode/settings.json",
        "doc/l3-dispatcher-planner/iteration/design-workspace-git-discovery.md"
      ]
    },
    {
      "id": "l3-dispatcher/flight-actions",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "本轮只补充 IDE 仓库发现与 CMake 源码定位，以及相应实施记录；未改变本契约的源码实现、运行接口、行为要求或父子登记。",
      "evidence": [
        "specs/implemented/inner/workspace-layout.spec.md",
        ".vscode/settings.json",
        "doc/l3-dispatcher-planner/iteration/design-workspace-git-discovery.md"
      ]
    },
    {
      "id": "development-workflow/l3-coding-style",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "本轮只补充 IDE 仓库发现与 CMake 源码定位，以及相应实施记录；未改变本契约的源码实现、运行接口、行为要求或父子登记。",
      "evidence": [
        "specs/implemented/inner/workspace-layout.spec.md",
        ".vscode/settings.json",
        "doc/l3-dispatcher-planner/iteration/design-workspace-git-discovery.md"
      ]
    },
    {
      "id": "l3-dispatcher/core-boundary",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "本轮只补充 IDE 仓库发现与 CMake 源码定位，以及相应实施记录；未改变本契约的源码实现、运行接口、行为要求或父子登记。",
      "evidence": [
        "specs/implemented/inner/workspace-layout.spec.md",
        ".vscode/settings.json",
        "doc/l3-dispatcher-planner/iteration/design-workspace-git-discovery.md"
      ]
    },
    {
      "id": "l3-dispatcher/execution-seam",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "本轮只补充 IDE 仓库发现与 CMake 源码定位，以及相应实施记录；未改变本契约的源码实现、运行接口、行为要求或父子登记。",
      "evidence": [
        "specs/implemented/inner/workspace-layout.spec.md",
        ".vscode/settings.json",
        "doc/l3-dispatcher-planner/iteration/design-workspace-git-discovery.md"
      ]
    },
    {
      "id": "l3-dispatcher/l4-rpc",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "本轮只补充 IDE 仓库发现与 CMake 源码定位，以及相应实施记录；未改变本契约的源码实现、运行接口、行为要求或父子登记。",
      "evidence": [
        "specs/implemented/inner/workspace-layout.spec.md",
        ".vscode/settings.json",
        "doc/l3-dispatcher-planner/iteration/design-workspace-git-discovery.md"
      ]
    },
    {
      "id": "l3-dispatcher/migration-protocol",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "本轮只补充 IDE 仓库发现与 CMake 源码定位，以及相应实施记录；未改变本契约的源码实现、运行接口、行为要求或父子登记。",
      "evidence": [
        "specs/implemented/inner/workspace-layout.spec.md",
        ".vscode/settings.json",
        "doc/l3-dispatcher-planner/iteration/design-workspace-git-discovery.md"
      ]
    },
    {
      "id": "l3-dispatcher/package-layout",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "本轮只补充 IDE 仓库发现与 CMake 源码定位，以及相应实施记录；未改变本契约的源码实现、运行接口、行为要求或父子登记。",
      "evidence": [
        "specs/implemented/inner/workspace-layout.spec.md",
        ".vscode/settings.json",
        "doc/l3-dispatcher-planner/iteration/design-workspace-git-discovery.md"
      ]
    },
    {
      "id": "l3-dispatcher/ros-adapter-boundary",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "本轮只补充 IDE 仓库发现与 CMake 源码定位，以及相应实施记录；未改变本契约的源码实现、运行接口、行为要求或父子登记。",
      "evidence": [
        "specs/implemented/inner/workspace-layout.spec.md",
        ".vscode/settings.json",
        "doc/l3-dispatcher-planner/iteration/design-workspace-git-discovery.md"
      ]
    },
    {
      "id": "l3-dispatcher/skill-contract",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "本轮只补充 IDE 仓库发现与 CMake 源码定位，以及相应实施记录；未改变本契约的源码实现、运行接口、行为要求或父子登记。",
      "evidence": [
        "specs/implemented/inner/workspace-layout.spec.md",
        ".vscode/settings.json",
        "doc/l3-dispatcher-planner/iteration/design-workspace-git-discovery.md"
      ]
    },
    {
      "id": "l3-dispatcher/tool-plane",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "本轮只补充 IDE 仓库发现与 CMake 源码定位，以及相应实施记录；未改变本契约的源码实现、运行接口、行为要求或父子登记。",
      "evidence": [
        "specs/implemented/inner/workspace-layout.spec.md",
        ".vscode/settings.json",
        "doc/l3-dispatcher-planner/iteration/design-workspace-git-discovery.md"
      ]
    },
    {
      "id": "observability/log",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "本轮只补充 IDE 仓库发现与 CMake 源码定位，以及相应实施记录；未改变本契约的源码实现、运行接口、行为要求或父子登记。",
      "evidence": [
        "specs/implemented/inner/workspace-layout.spec.md",
        ".vscode/settings.json",
        "doc/l3-dispatcher-planner/iteration/design-workspace-git-discovery.md"
      ]
    },
    {
      "id": "development-workflow/contract-sync",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "本轮只补充 IDE 仓库发现与 CMake 源码定位，以及相应实施记录；未改变本契约的源码实现、运行接口、行为要求或父子登记。",
      "evidence": [
        "specs/implemented/inner/workspace-layout.spec.md",
        ".vscode/settings.json",
        "doc/l3-dispatcher-planner/iteration/design-workspace-git-discovery.md"
      ]
    },
    {
      "id": "l3-dispatcher",
      "clauses": [
        "边界"
      ],
      "status": "unchanged",
      "reason": "本轮只补充 IDE 仓库发现与 CMake 源码定位，以及相应实施记录；未改变本契约的源码实现、运行接口、行为要求或父子登记。",
      "evidence": [
        "specs/implemented/inner/workspace-layout.spec.md",
        ".vscode/settings.json",
        "doc/l3-dispatcher-planner/iteration/design-workspace-git-discovery.md"
      ]
    },
    {
      "id": "observability",
      "clauses": [
        "边界"
      ],
      "status": "unchanged",
      "reason": "本轮只补充 IDE 仓库发现与 CMake 源码定位，以及相应实施记录；未改变本契约的源码实现、运行接口、行为要求或父子登记。",
      "evidence": [
        "specs/implemented/inner/workspace-layout.spec.md",
        ".vscode/settings.json",
        "doc/l3-dispatcher-planner/iteration/design-workspace-git-discovery.md"
      ]
    },
    {
      "id": "topology",
      "clauses": [
        "边界"
      ],
      "status": "unchanged",
      "reason": "本轮只补充 IDE 仓库发现与 CMake 源码定位，以及相应实施记录；未改变本契约的源码实现、运行接口、行为要求或父子登记。",
      "evidence": [
        "specs/implemented/inner/workspace-layout.spec.md",
        ".vscode/settings.json",
        "doc/l3-dispatcher-planner/iteration/design-workspace-git-discovery.md"
      ]
    },
    {
      "id": "runtime/drone-remote-build",
      "clauses": [
        "术语与身份",
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "本轮只补充 IDE 仓库发现与 CMake 源码定位，以及相应实施记录；未改变本契约的源码实现、运行接口、行为要求或父子登记。",
      "evidence": [
        "specs/implemented/inner/workspace-layout.spec.md",
        ".vscode/settings.json",
        "doc/l3-dispatcher-planner/iteration/design-workspace-git-discovery.md"
      ]
    },
    {
      "id": "l3-dispatcher/scenegraph",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "本轮只补充 IDE 仓库发现与 CMake 源码定位，以及相应实施记录；未改变本契约的源码实现、运行接口、行为要求或父子登记。",
      "evidence": [
        "specs/implemented/inner/workspace-layout.spec.md",
        ".vscode/settings.json",
        "doc/l3-dispatcher-planner/iteration/design-workspace-git-discovery.md"
      ]
    },
    {
      "id": "l3-dispatcher/tracking",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "本轮只补充 IDE 仓库发现与 CMake 源码定位，以及相应实施记录；未改变本契约的源码实现、运行接口、行为要求或父子登记。",
      "evidence": [
        "specs/implemented/inner/workspace-layout.spec.md",
        ".vscode/settings.json",
        "doc/l3-dispatcher-planner/iteration/design-workspace-git-discovery.md"
      ]
    },
    {
      "id": "runtime/station-telemetry",
      "clauses": [
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "本轮只补充 IDE 仓库发现与 CMake 源码定位，以及相应实施记录；未改变本契约的源码实现、运行接口、行为要求或父子登记。",
      "evidence": [
        "specs/implemented/inner/workspace-layout.spec.md",
        ".vscode/settings.json",
        "doc/l3-dispatcher-planner/iteration/design-workspace-git-discovery.md"
      ]
    },
    {
      "id": "runtime/unity-k3s-bringup",
      "clauses": [
        "输入、输出与配置",
        "归属与依赖"
      ],
      "status": "unchanged",
      "reason": "本轮只补充 IDE 仓库发现与 CMake 源码定位，以及相应实施记录；未改变本契约的源码实现、运行接口、行为要求或父子登记。",
      "evidence": [
        "specs/implemented/inner/workspace-layout.spec.md",
        ".vscode/settings.json",
        "doc/l3-dispatcher-planner/iteration/design-workspace-git-discovery.md"
      ]
    },
    {
      "id": "runtime",
      "clauses": [
        "边界"
      ],
      "status": "unchanged",
      "reason": "本轮只补充 IDE 仓库发现与 CMake 源码定位，以及相应实施记录；未改变本契约的源码实现、运行接口、行为要求或父子登记。",
      "evidence": [
        "specs/implemented/inner/workspace-layout.spec.md",
        ".vscode/settings.json",
        "doc/l3-dispatcher-planner/iteration/design-workspace-git-discovery.md"
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
      "reason": "补充角色目录迁移后的 IDE 仓库发现要求及设置文件归属，保持 L3 内置、L2/L4 独立检出的版本边界。",
      "evidence": [
        "specs/implemented/inner/workspace-layout.spec.md",
        ".vscode/settings.json",
        "doc/l3-dispatcher-planner/iteration/design-workspace-git-discovery.md"
      ]
    }
  ]
}
```

## 6. 删除清单

删除 IDE 设置中的旧 L3 绝对定位；替换整目录忽略规则为仅放行共享设置文件。Git 元数据和独立检出均不删除。

## 7. 实施步骤

P0：读取治理契约、调查 Git 事实与插件扫描机制、捕获基线并落盘方案。
P1：先补充布局契约，再修改共享工作区设置及忽略例外。
P2：在原迁移记录登记遗漏与修复，说明门禁和界面复查尚未执行。回退仅恢复本轮设置、忽略规则和文档差异，不操作检出内容。

## 8. 验收标准

预期源代码管理面板显示父仓库、L2、L4；L3 改动归父仓库。IDE 可能需要执行 Developer: Reload Window 重新发现。未获许可不运行验收测试、结构或同步门禁，不宣称界面恢复已验收。调查中的 Git 只读命令仅用于故障定位。

## 9. 风险与对策

IDE 已关闭仓库或保存旧缓存时可能仍需重新打开窗口；显式扫描路径避免依赖旧根目录缓存。仅共享可移植的设置，不入库个人全局配置。历史路径移动仍为未提交差异，不自动暂存或提交以改变显示。

## 10. 修改点清单汇总

- `.vscode/settings.json`：显式发现独立仓库，修复 CMake 路径。
- `.gitignore`：仅放行工作区共享设置。
- `specs/implemented/inner/workspace-layout.spec.md`：补充 IDE 同轮迁移要求与文件绑定。
- 两份实施方案：记录修复范围、调查证据与待检查项。

### 实际实施记录

已写入独立检出扫描路径与可移植 CMake 定位，调整设置文件的忽略例外，并同步 WL6、WL10 及布局契约关联。未修改独立 L2/L4 的源码或 Git 元数据，未操作分支、远端、暂存区与提交。未运行 IDE 界面验收、测试或结构及同步门禁；仍待许可执行相关检查。
