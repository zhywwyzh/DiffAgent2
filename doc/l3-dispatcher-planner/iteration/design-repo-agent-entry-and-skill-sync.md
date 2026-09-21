# 仓库级 agent 入口与技能同步 方案

> 摘要：为新版编排仓库补上两项 agent 基础设施——根 `CODEBUDDY.md`
> （会话开始即注入 system prompt：限定阅读范围 + 提前给出硬约束）与
> `.codebuddy/sync-skills.sh`（把 `.trae/skills` 幂等同步进
> `~/.codebuddy/skills`），并放开 `.trae/skills/` 的跟踪以让新增技能入库。
> 范围：仓库根 `CODEBUDDY.md`（新增）、`.codebuddy/sync-skills.sh`（新增）、
> `.gitignore`（修改）。依据来源：用户 2026-09-20 指令「技能需要，但是限制
> 阅读和提前给出 system prompt 的 CODEBUDDY.md 也需要」；姊妹篇
> `20260915-20260917/design-dispatcher-privacy-gate-cleanup.md`（机器特定值口径）。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-20 |
| 目标路径 | 仓库根 `CODEBUDDY.md`、`.codebuddy/sync-skills.sh`、`.gitignore` |
| 状态 | done（P0–P2 已执行，见 §11） |
| 关联文档 | `AGENTS.md`、`specs/README.md`、`specs/implemented/inner/entity-naming.spec.md`、`doc/l3-dispatcher-planner/rest/README.md`、旧版 `CODEBUDDY.md`、旧版 `.codebuddy/{sync-skills.sh,rules/repo-conventions/RULE.mdc}` |

> **落盘位置说明**：本方案属仓库级（非 l3 领域）基础设施，但
> `AGENTS.md` 代码优化工作流 §2 只承认 `doc/<workspace>/iteration/`
> （当前唯一 workspace = l3-dispatcher-planner），故落此目录；
> 文件名沿用同目录的 `design-<topic>.md` 惯例。

## 1. 背景与动机

- **用户指令**：技能（同步）需要；限制阅读、提前给出 system prompt 的
  `CODEBUDDY.md` 也需要。
- **新版现状**：根目录无 `CODEBUDDY.md`、无 `.codebuddy/`（实测 `ls -a`）。
- **旧版为何如此设计**：旧版根目录没有 `AGENTS.md`，约定文件都在
  `diff-dockers/` 子目录；而 CodeBuddy 的自动加载只看项目根的
  `AGENTS.md` / `CODEBUDDY.md`（旧版 `RULE.mdc#L19` 明写）→ 必须用根
  `CODEBUDDY.md` 做入口指针，用 `.codebuddy/rules/*.mdc`
  （`alwaysApply: true`）做常驻规则，用 `.codebuddy/sync-skills.sh` 补技能加载。
- **新版差异**：新版**根目录已有 `AGENTS.md`**，自动加载已生效。因此新版
  `CODEBUDDY.md` 的价值不是「补指针」，而正是用户点名的两件事：
  **限制阅读**（默认不读清单 + 禁止项）与**提前给出 system prompt**
  （会话开始即注入可执行门与边界）。

## 2. 现状事实（问题清单）

> 每条带「文件路径 + 行号」证据，行号基于 2026-09-20 工作区状态。

### 2.1 缺失项

- [ ] 新版仓库根无 `CODEBUDDY.md`、无 `.codebuddy/`（`ls -a` 实测，根目录仅
  `AGENTS.md` `doc/` `specs/` `l3-dispatcher-planner/` `l4-agent/` `.trae/` `.vscode/`）。
- [ ] `~/.codebuddy/skills/` 现有 `gitlab-issue`、`gitlab-pull`（旧版 17:28
  同步），新版 `.trae/skills/{github-issue,github-pull}` **未同步**。

### 2.2 旧版资产不可直接搬运

- [ ] `Diff-Agent2/.codebuddy/sync-skills.sh#L12` —
  `WORKSPACE="/home/zhywwyzh/workspace/Diff-Agent2"`：硬编码主机绝对路径，
  违反 `AGENTS.md` 硬性约束 §1（机器特定值不入库）。
- [ ] `Diff-Agent2/CODEBUDDY.md#L10-L13` — 指向 `diff-dockers/AGENTS.md`、
  `drone_projects/*`、`station_projects/*`；新版目录形态不同，路径全部失效。
- [ ] `Diff-Agent2/.codebuddy/sync-skills.sh#L15-L20` — 源列表含用户级
  `${HOME}/.trae/skills`、`${HOME}/.agent/skills`（新版无此约定）。

### 2.3 技能可跟踪性缺口

- [ ] `.gitignore#L44-L46` — `# basic` 段含 `.trae/`；实测 `git ls-files`
  仅两个 `SKILL.md` 被跟踪（历史遗留），**新增技能不会被纳入版本控制**。
- [ ] `.vscode/settings.json#L2` 含主机绝对路径，但 `.vscode/` 已被忽略且
  未被跟踪 → 不构成入库风险，仅登记，不在本方案处置。

### 2.4 阅读范围失控风险（本方案的直接动因）

- [ ] `doc/l3-dispatcher-planner/iteration/` 现有 29 个 md（含单文件 55 KB
  级方案）、`doc/l3-dispatcher-planner/rest/` 3 个；均为冻结过程材料，
  但目录名不含「历史」字样，agent 易误当现行契约通读。
- [ ] `specs/implemented/` 25 个 md；`AGENTS.md` 未声明「禁止通读
  `specs/`」与「默认不读过程材料」。
- [ ] 现行入口散落三处：`AGENTS.md` §契约加载、`specs/README.md` §规则、
  `doc/l3-dispatcher-planner/rest/README.md` §入口——无单一「开工前必读 +
  默认不读」清单可注入 system prompt。

## 3. 目标与约束

- **目标**：
  1. 根 `CODEBUDDY.md`：会话开始即注入，给出「必读入口表 + 默认不读清单 +
     禁止项 + 可执行门命令」，使 agent 不越界阅读。
  2. `.codebuddy/sync-skills.sh`：把 `.trae/skills/**` 幂等同步进
     `~/.codebuddy/skills/`，**零机器特定值**（工作区根由脚本自身位置解析）。
  3. 技能可跟踪：让新增技能默认能进版本控制。
- **Non-Goals**：
  - 不改 `AGENTS.md`（不在默认目标树内；如需拆分其表述另行请示）。
  - 不改任何 `specs/**`（本方案不产生契约变更）。
  - 不改 l3 代码，不改 `l4-agent`（独立嵌套仓库）。
  - 不搬运旧版 `CODEBUDDY.md` 的 `diff-dockers/` 路径表。
  - 不新增 `.codebuddy/rules/*.mdc`（见 §4.4 裁决）。
- **硬边界**：
  - 文档简体中文（`AGENTS.md` §8）；不写主机绝对路径/个人用户名/凭据（§1）。
  - `CODEBUDDY.md` 只做入口与边界，不复制 `AGENTS.md` / spec 正文
    （`AGENTS.md` 首段「本文件只做约束与指引，不重复它们」）。
  - 权威顺序：`specs/` > `AGENTS.md` > `CODEBUDDY.md`。
  - 禁止新设计转接器；被替代项直接删除，不留 shim 或注释桩。

## 4. 方案决策

### 4.1 目标文件树

```
Diff-Agent2.0/
  CODEBUDDY.md              # 新增：会话开始注入的入口与阅读边界
  .codebuddy/
    sync-skills.sh          # 新增：技能同步（路径自解析，无机器特定值）
  .gitignore                # 修改：放开 .trae/skills/ 跟踪
```

### 4.2 `CODEBUDDY.md` 内容骨架（全文草稿，待裁决）

````markdown
# 工作区约定入口 — DiffAgent2 新版

> 本文件在会话开始时被注入 system prompt，用于**限定阅读范围**并提前给出
> 硬约束。它只做入口、边界与命令；事实与契约归 `AGENTS.md` 与 `specs/`。
> 权威顺序：`specs/` > `AGENTS.md` > 本文件。

## 1. 开工前必读

| 场景 | 必读 |
|------|------|
| 任何改动 | `AGENTS.md`（硬约束、权威顺序、代码优化工作流） |
| 涉及契约 | `specs/README.md` + 命中任务的根契约 + 其 `## Inner contracts` 表 |
| l3 任务 | `specs/implemented/l3-dispatcher.spec.md` + 该表列出的叶契约 |
| 涉及保留项 / 字段删除 / 返航 / 动作武装 / VLA 调试 / 急停悬停 | `doc/l3-dispatcher-planner/rest/README.md` 及其台账对应条目 |
| l4 任务 | `l4-agent/AGENTS.md`（独立嵌套仓库，边界以其正文为准） |
| 改 `specs/**` | `specs/README.md`（生命周期、header、登记规则） |

## 2. 默认不读（限制阅读）

以下为冻结过程材料或未采纳内容，**除非用户明确要求或任务直接命中，
否则不读**：

- `doc/**/iteration/**` — 历史方案与执行记录；现行契约已抽到 `specs/`。
- `doc/**/rest/**` — 迁移台账；仅在 §1 命中的场景读对应条目，不通读。
- `specs/implemented/{architecture,process}/**` — 决策记录。
- `specs/proposed/**`、`specs/rejected/**`、`specs/archived/**`。
- `AGENTS.md` 中的编号迭代记录。

## 3. 禁止

- 禁止通读 `specs/`（25 个文件）或全仓扫描式阅读；只读 §1 命中的根 + 叶。
- 禁止从 `doc/**/iteration/**` 的历史方案反推「现行契约」——现行契约只以
  `specs/` 为准。
- 禁止把 `rest/` 台账当作「生产能力已实现」的证据。
- 需要超出 §1 的阅读时，先问用户，不要自行展开。

## 4. 门与纪律（指针式摘要，权威在 `AGENTS.md` §硬性约束）

- **spec 先行**：契约变更先落 `specs/`，再改实现；代码与 spec 冲突时修实现。
- **隐私门禁**：`*.md` 不写主机绝对路径、个人用户名、密码/令牌/私钥；
  公开仓库 URL 与其仓主名不属凭据。
- **文档一律简体中文**。
- **验收测试**：除非使用者明确许可，跳过测试与验证性验收（`AGENTS.md` §9）。
- **提交**用 `git commit --no-verify`；不安装、不重新启用预提交钩子。
- **内置子树** `l3-dispatcher-planner/` 的改动不与父仓库一起提交，需显式指令。
- **无转接器、过期必删**：被替代的旧接口直接删除，不留 shim 或注释桩。

## 5. 技能同步

```bash
bash .codebuddy/sync-skills.sh
```

把 `.trae/skills/**` 幂等同步进 `~/.codebuddy/skills/`（CodeBuddy 只从用户级
技能目录加载技能）。新增或更新技能后重跑一次。

## 6. 冲突处理

用户要求与 `AGENTS.md` / `specs/` 冲突时：**停下**，引用双方原文与出处
（`文件:行`），请用户裁决按哪一方执行，不自行裁决。
````

### 4.3 `sync-skills.sh` 关键设计

```bash
#!/usr/bin/env bash
# Entity: station-host
# Invoked: directly by the operator
# sync-skills — 把 .trae/skills 幂等同步进 CodeBuddy 用户级技能目录
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${CODEBUDDY_SKILLS_DIR:-${HOME}/.codebuddy/skills}"
SOURCES=("${ROOT}/.trae/skills" "${ROOT}/.agent/skills")
```

- **路径自解析**：`ROOT` 由 `BASH_SOURCE` 上溯一级得出，删除旧版 `WORKSPACE`
  硬编码（§2.2）。
- **零机器特定值**：仅出现 `${HOME}` 等环境变量与仓库相对路径。
- **幂等**：对每个含 `SKILL.md` 的技能目录 `rm -rf "${DEST}/${name}"` 后
  `cp -r`；重复运行即完成同步。
- **源集合收敛**：保留项目级 `.trae/skills`（现有）与 `.agent/skills`（预留，
  不存在则跳过）；**删除**旧版的用户级源两项（§2.2、§4.4）。
- **实体头**：按 `entity-naming.spec.md#L14-L18` 取 `station-host`，并补
  `# Invoked:`（§2.1 要求）。`.codebuddy/` 不在该 spec §2.2 强制的顶层脚本
  目录清单内，故文件名不带实体前缀，沿用 `sync-skills.sh`。
- 输出每次同步清单与总数，便于核对（不静默覆盖）。

### 4.4 待裁决项

| 项 | 备选 | 建议 | 依据 |
|----|------|------|------|
| `.codebuddy/rules/repo-conventions/RULE.mdc` | 建 / 不建 | **不建** | 用户点名的是 `CODEBUDDY.md`；常驻规则正文已由根 `AGENTS.md` 承担，再建一份形成双权威，违反「一个主题一个权威」 |
| `.gitignore` 放开 `.trae/skills/` | 改 / 不改（改用 `git add -f`） | **改** | 不依赖人工 `-f`，新增技能默认可跟踪；精确放开，不整目录放开 |
| 技能源是否保留用户级 `~/.trae/skills`、`~/.agent/skills` | 保留 / 删除 | **删除** | 新版无此约定；过期必删，且避免工作区外的不确定输入 |

### 4.5 命名规范表

| 类型 | 规范 | 示例 |
|------|------|------|
| 脚本 | `.codebuddy/` 下不带实体前缀（不在 `entity-naming` §2.2 强制清单内） | `.codebuddy/sync-skills.sh` |
| 脚本头 | 必带 `# Entity:` 与 `# Invoked:` | `# Entity: station-host` |
| 根入口文档 | 全大写文件名，仓库根唯一 | `CODEBUDDY.md` |
| 方案文档 | `design-<topic>.md` | `design-repo-agent-entry-and-skill-sync.md` |

### 4.6 旧接口 → 删除

- 旧版脚本的 `WORKSPACE` 硬编码变量：删除，不保留兼容分支。
- 旧版脚本的用户级源两项：删除，不留注释桩。
- 旧版 `RULE.mdc`：不迁移（§4.4），不在新版留占位文件。

## 5. 迁移映射表

| 旧路径/命名 | 新路径/命名 | 动作 | 备注 |
|-------------|-------------|------|------|
| `Diff-Agent2/CODEBUDDY.md` | `CODEBUDDY.md` | rewrite | 按新版目录结构重写；旧版 `diff-dockers/` 路径表全部废弃 |
| `Diff-Agent2/.codebuddy/sync-skills.sh` | `.codebuddy/sync-skills.sh` | rewrite | 去硬编码路径、去用户级源、补 `# Invoked:` |
| `Diff-Agent2/.codebuddy/rules/repo-conventions/RULE.mdc` | — | delete | 不迁移（§4.4） |
| `.trae/skills/{github-issue,github-pull}` | `~/.codebuddy/skills/*` | sync | 由脚本执行，不入版本控制 |

## 6. 删除清单

| 删除项 | 理由 |
|--------|------|
| 旧版脚本 `WORKSPACE` 硬编码（`sync-skills.sh#L12`） | 机器特定值，违反 `AGENTS.md` §1 |
| 旧版脚本用户级源两项（`sync-skills.sh#L18-L19`） | 新版无此约定 |
| 旧版 `RULE.mdc` 不迁移 | 避免与根 `AGENTS.md` 双权威 |

## 7. 实施步骤（P0–P2）

### P0 — 根入口文档

- 范围：新增 `CODEBUDDY.md`（§4.2 全文）。
- 行为不变式：不改任何既有文件；不改 `AGENTS.md`。
- 验收：文件存在；`grep -n "/home/" CODEBUDDY.md` 零命中；所引用路径全部可解析。
- 回退：删除该文件。

### P1 — 技能同步脚本

- 范围：新增 `.codebuddy/sync-skills.sh`（§4.3）；`chmod +x`；执行一次同步。
- 行为不变式：不删除 `~/.codebuddy/skills/` 下本次源集合之外的既有技能。
- 验收：脚本输出 `total: 2 skill(s) synced`；`~/.codebuddy/skills/` 出现
  `github-issue`、`github-pull`，且 `gitlab-issue`、`gitlab-pull` 未被删。
- 回退：删除脚本；用户级目录按需手工清理。

### P2 — 技能跟踪与提交

- 范围：`.gitignore` 的 `# basic` 段由 `.trae/` 改为 `.trae/*` +
  `!.trae/skills/`；确认两个既有 `SKILL.md` 仍在跟踪列表。
- 行为不变式：`.trae/` 下 `skills/` 以外的内容仍被忽略。
- 验收：`git check-ignore -v .trae/skills/<新技能>/SKILL.md` 不再命中；
  `git status` 未出现 `.trae/` 下非技能文件。
- 回退：`git checkout -- .gitignore`。

## 8. 验收标准

> **统一声明**：除非使用者明确许可，否则跳过验收测试工作（`AGENTS.md` 硬性约束 §9）。

- [ ] 根目录 `ls -a` 含 `CODEBUDDY.md` 与 `.codebuddy/sync-skills.sh`
- [ ] `grep -rn "/home/" CODEBUDDY.md .codebuddy/` 零命中
- [ ] `bash .codebuddy/sync-skills.sh` 输出 `total: 2 skill(s)`
- [ ] `~/.codebuddy/skills/` 含 `github-issue`、`github-pull`，且旧有技能未被删除
- [ ] `git check-ignore -v .trae/skills/<新技能>/SKILL.md` 不再命中
- [ ] `CODEBUDDY.md` 与 `AGENTS.md` / `specs/` 无正文级重复（人工比对，仅入口与边界）
- [ ] 未运行任何 pytest（`AGENTS.md` §9）

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| `CODEBUDDY.md` 与 `AGENTS.md` 内容重叠 | 双权威、后续漂移 | 只写入口/边界/命令；硬约束以一行指针引用 `AGENTS.md` §硬性约束 |
| 与 `AGENTS.md`「l3 任务读全部叶契约」口径冲突 | 越权放宽阅读 | 不改该口径；`CODEBUDDY.md` 只新增「默认不读过程材料」，不动契约加载规则 |
| 同步脚本覆盖用户级同名技能 | 误删他人技能 | `DEST` 只按源技能名 `rm -rf`；运行前先 `ls`，输出每次同步清单 |
| `~/.codebuddy/skills/` 被多工作区共用 | 技能串味 | 只增不改；输出清单可核对；`CODEBUDDY_SKILLS_DIR` 可覆盖目标目录 |
| `.trae/*` 放开过宽 | 误跟踪临时文件 | 用 `.trae/*` + `!.trae/skills/` 精确放开，并逐条验收 |
| `CODEBUDDY.md` 被自动加载但与 `AGENTS.md` 同时注入 | 上下文冗余 | 严格保持「入口 + 边界」，总量控制在 100 行内 |

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|------|------|------|
| `CODEBUDDY.md` | 新增 | P0：会话开始注入的入口与阅读边界（§4.2） |
| `.codebuddy/sync-skills.sh` | 新增 | P1：技能同步，路径自解析、零机器特定值（§4.3） |
| `.gitignore` | edit | P2：`# basic` 段 `.trae/` → `.trae/*` + `!.trae/skills/` |
| `~/.codebuddy/skills/**` | sync（不入库） | P1：脚本执行结果，非仓库文件 |

## 11. 执行记录（2026-09-20）

> 用户 2026-09-20 裁决「可以开始创建了」，§4.4 三个待裁决项按建议执行：
> 不建 `RULE.mdc`、放开 `.trae/skills/` 跟踪、删除用户级源。测试执行按 §8
> 统一声明跳过。

### P0 — 根入口文档

- 新增 `CODEBUDDY.md`（§4.2 全文落地，共 6 节：开工前必读 / 默认不读 /
  禁止 / 门与纪律 / 技能同步 / 冲突处理）。

### P1 — 技能同步脚本

- 新增 `.codebuddy/sync-skills.sh`，`chmod +x`；`ROOT` 由 `BASH_SOURCE`
  上溯解析，源集合收敛为项目级 `.trae/skills`（现有）+ `.agent/skills`（预留）。
- 执行实测：`synced: github-issue`、`synced: github-pull`，
  `total: 2 skill(s) synced to ~/.codebuddy/skills`；
  `~/.codebuddy/skills/` 现有 `github-issue`、`github-pull`、`gitlab-issue`、
  `gitlab-pull` 与四个文档类技能 —— **旧有技能未被删除**，符合 §7 P1 不变式。

### P2 — 技能跟踪

- `.gitignore` 的 `# basic` 段由 `.trae/` 改为 `.trae/*` + `!.trae/skills/`
  并附一行注释说明放开理由。

### 验收实测（2026-09-20，静态）

- `grep -rn "/home/" CODEBUDDY.md .codebuddy/` → **零命中**（§8-2）。
- `git check-ignore -v .trae/skills/<新技能>/SKILL.md` → 不再命中（§8-5）。
- 反向校验：`git check-ignore -v .trae/rules/foo.md` 仍命中 `.gitignore:46:.trae/*`；
  `.vscode/settings.json` 仍命中 `.gitignore:48:.vscode/` → 放开范围精确（§7 P2 不变式）。
- `git status --short` 出现 `.gitignore`(M)、`.codebuddy/`(??)、`CODEBUDDY.md`(??)，
  `.trae/` 下无非技能文件被暴露。
- 未运行 pytest（`AGENTS.md` §9）；`CODEBUDDY.md` 与 `AGENTS.md` 无正文级重复
  （§8 末项，人工比对）。
