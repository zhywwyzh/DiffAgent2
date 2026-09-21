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
