# dispatcher 隐私与文档门禁清理 方案

> 摘要：把纳入版本控制的文档里**主机绝对路径与个人标识**清理干净，满足 `AGENTS.md`
> 硬性约束 1/2 与 `topology` 不变量（「任何个人或机器特定的具体主机值都不进入纳入
> 版本控制的文档」）。零代码改动、零语义改动，只做**标识替换**；公开服务标识
> （GitHub 仓库 URL/仓主名）保留，其措辞收敛归 S1。
>
> 归属：总纲 `design-dispatcher-architecture-stabilization.md` 的 **S0** 期。

## 0. 元信息

| 项 | 值 |
|----|----|
| 日期 | 2026-09-12 |
| 目标路径 | `AGENTS.md`、`doc/l3-dispatcher-planner/iteration/*.md`、`.trae/skills/github-{issue,pull}/SKILL.md` |
| 状态 | done（2026-09-12 执行完毕，见 §11 附录） |
| 前置 | 无（可与 S1 并行；但**先于**本套其余各期，保证后续方案与施工脚本不再写绝对路径） |
| 关联文档 | 总纲 §2.C、§4.8；契约：`AGENTS.md` 硬性约束 1/2、`specs/implemented/topology.spec.md` 不变量、`specs/implemented/inner/entity-naming.spec.md` §2.3 |
| 需放行 | **是**：`AGENTS.md` 与 `.trae/skills/` 不在默认编辑目标树（`l3-dispatcher-planner/`）内 |

## 1. 背景与动机

`AGENTS.md` 把「文档不写个人凭据」列为**不可协商约束**：`*.md` 只写角色名，
个人用户名、密码、令牌绝不进入纳入版本控制的文件；检索模式维护在主机本地、
不写入纳入版本控制的文件。`topology` 不变量进一步要求「任何个人或机器特定的
具体主机值都不进入纳入版本控制的文档」。

现状：全仓纳入版本控制的文档中，主机绝对路径（含主机用户名）共 **67 行命中**，
分布在 6 个文件；其中约 3/4 是施工脚本里的 `<host-abs-path>` 绝对路径，
使文档在不同主机上不可复跑、且把主机用户名写进了公开仓库。

本期的目标不是「改历史结论」，而是**机械替换标识**，并把「后续文档不得写绝对路径」
变成可判定门禁（总纲 §4.4 A4）。

## 2. 现状事实（问题清单）

> 逐行已核；计数为**行命中数**（同一行多次出现只计 1）。路径前缀省略为
> `<new-repo-root> = 新版检出根`、`<old-repo-root> = DiffAgent2 旧版检出根`。

- [ ] `AGENTS.md` — 9 处（L10/L15/L27/L28/L39/L40/L41/L90/L93）：其中 **3 处为主机绝对路径**
      （L28 `<host-abs-path>/Diff-Agent2.0`、L39 同、L41 `<host-abs-path>/Diff-Agent2`），
      其余 6 处为公开仓库标识（`https://github.com/<owner>/DiffAgent2` 形式的仓主名/仓库名）。
- [ ] `doc/l3-dispatcher-planner/iteration/design-dispatcher-taskid-retirement-deps-migration.md` — 20 处
      （L14/L15 源与目标根、L236/L245/L246 施工 `cd`/`OLD=`/`NEW=`、L312-L320 `py_compile` 清单、
      L326/L327 `cmp` 清单、L344/L354/L355/L397 脚本内绝对路径）：**全部为主机绝对路径**。
- [ ] `doc/l3-dispatcher-planner/iteration/design-dispatcher-core-inference-migration.md` — 14 处
      （L18/L19、L367、L371/L372、L541/L542、L548/L549、L559、L569/L570、L619/L620）：全部为主机绝对路径。
- [ ] `doc/l3-dispatcher-planner/iteration/design-dispatcher-engine-narrow-core-trim.md` — 8 处
      （L333、L397、L405、L425/L426、L469/L470、L512）：全部为主机绝对路径。
- [ ] `.trae/skills/github-pull/SKILL.md` — 7 处（L3/L12/L24/L31/L32/L34/L37）：其中
      **4 处为主机绝对路径**（L24/L32/L34/L37），3 处为公开仓库/仓主标识（L3/L12/L31）。
- [ ] `.trae/skills/github-issue/SKILL.md` — 9 处（L3/L12/L38/L39/L49/L66/L87/L88 等）：**全部为公开仓库标识**，无主机路径。
- [ ] 合计：**67 处 = 49 处主机绝对路径（需替换）+ 18 处公开服务标识（保留）**。
- [ ] 反证（已核，无需改动）：`design-dispatcher-package-topology.md`、`design-dispatcher-engine-relocate-non-core.md`、
      `design-dispatcher-zenoh-transport-migration.md` 已用相对路径与 `<repo-name>` 占位，
      证明「文档不写绝对路径」在本仓库已有先例与可行写法。
- [ ] `specs/**` 与 `.trae/skills/` 下其余文件、`l3-dispatcher-planner/**` 代码与测试：**零命中**（本期新增的
      总纲亦零命中）。

## 3. 目标与约束

- **目标**：
  1. 把 49 处主机绝对路径替换为**相对路径或角色名占位**，使文档跨主机可读可复跑；
  2. 固化「文档不写主机绝对路径与个人标识」的可判定门禁（A4）；
  3. 保留公开服务标识，并把「凭据」与「公开服务标识」的边界写成可执行判定（措辞定稿归 S1）。
- **Non-Goals**：
  - 不改任何方案的历史结论、行号、验收命令语义（只替换路径前缀与主机标识）；
  - 不删除公开仓库 URL/仓主名（`github-issue`/`github-pull` 依赖它工作，且 `AGENTS.md` 的 issue 规则引用它）；
  - 不引入检索脚本文件到仓库（约束 2：检索模式维护在主机本地，不入库）；
  - 不迁移 `specs/tools/*` 门禁脚本（登记为后续轮次）。
- **硬边界**：
  - 只做标识替换，不做内容重写；替换后同一命令的相对路径语义必须等价；
  - 不新增「凭据占位映射表」等泄露载体；占位符只用角色名（`station-host` / 新版检出 / 旧版检出）；
  - 文档一律简体中文。

## 4. 方案决策

- **替换规则表**（唯一裁决）：

  | 类型 | 判定 | 替换为 | 示例 |
  |---|---|---|---|
  | 新版检出主机绝对路径 | 路径指向本仓库检出根 | `<new-repo-root>` 或（同文档上下文明确时）**相对路径** `l3-dispatcher-planner/…` | `<new-repo-root>/l3-dispatcher-planner/ros_packages/dispatcher/dispatcher/engine.py` |
  | 旧版检出主机绝对路径 | 路径指向旧版检出 | `<old-repo-root>`（角色名：DiffAgent2 旧版检出） | `<old-repo-root>/diff-dockers/drone_projects/l3-dispatcher-planner/ros_packages/dispatcher/` |
  | 施工脚本内的 `cd`/`OLD=`/`NEW=` | 见上两类 | `REPO_ROOT=<new-repo-root>` 形式，命令其余部分逐字不变 | `cd "$REPO_ROOT"` |
  | 主机用户名单独出现（非路径） | 指代执行主机 | 角色名 `station-host`（`entity-naming` §1） | 「station-host 上的检出」 |
  | 公开仓库 URL / 仓主名 / 仓库标识 | 公开服务标识 | **保留**（措辞定稿见 S1） | `https://github.com/<owner>/DiffAgent2`、`<owner>/DiffAgent2` |
  | 私有凭据（密码/令牌/私钥） | 任意形式 | **不存在**（本期复核为零命中，若发现立即删除并上报） | — |

- **验证方式裁决**：约束 2 要求检索模式在主机本地。因此本期**不在仓库内建立检索脚本**，
  只在本方案内以占位符 `<personal-id>` / `<host-abs-path>` 描述判定，执行时由 station-host
  本地模式代入。执行记录只写「命中数」，不写模式、不写命中内容。
- **历史文档处置裁决**：三份已 `done` 的方案（`core-inference` / `narrow-core-trim` / `taskid-retirement`）
  **就地替换标识**，不重写、不归档。理由：`specs/README.md` 的「正文不再维护」针对 `specs/` 下决策
  记录；`doc/` 下的方案属过程材料，其绝对路径属**缺陷**而非历史事实，机械替换不改变任何结论。
- **放行边界裁决**：未取得放行时，本期只改 `doc/**`；`AGENTS.md` 与 `.trae/skills/` 保持原状并在
  总纲登记为未完成项（不得因「未放行」而降级为永久豁免）。

## 5. 迁移映射表

> 行号为现状实测；动作均为「标识替换」。

| 文件 | 行 | 动作 | 备注 |
|---|---|---|---|
| `AGENTS.md` | L28、L39、L41 | 替换绝对路径 → `<new-repo-root>` / `<old-repo-root>` | 该文件「新旧版本命名」一节的区分能力必须保持 |
| `AGENTS.md` | L10、L15、L27、L40、L90、L93 | 保留 | 公开仓库标识 |
| `doc/…/design-dispatcher-taskid-retirement-deps-migration.md` | L14、L15、L236、L245、L246、L312-L320、L326、L327、L344、L354、L355、L397 | 替换 → `<new-repo-root>` / `<old-repo-root>` 或相对路径 | L245/L326 的 `OLD=`/`NEW=` 改为 `OLD=<old-repo-root>/…`、`NEW=<new-repo-root>/…` |
| `doc/…/design-dispatcher-core-inference-migration.md` | L18、L19、L367、L371、L372、L541、L542、L548、L549、L559、L569、L570、L619、L620 | 同上 | 同上 |
| `doc/…/design-dispatcher-engine-narrow-core-trim.md` | L333、L397、L405、L425、L426、L469、L470、L512 | 同上 | 同上 |
| `.trae/skills/github-pull/SKILL.md` | L24、L32、L34、L37 | 替换 → `<new-repo-root>/…` | L34 的 `git clone … <path>` 目标路径同改 |
| `.trae/skills/github-pull/SKILL.md` | L3、L12、L31 | 保留 | L31 为示例仓主名 |
| `.trae/skills/github-issue/SKILL.md` | 全部 9 处 | 保留 | 公开仓库标识 |

## 6. 删除清单

| 删除项 | 理由 |
|---|---|
| 文档中的 `<host-abs-path>` 绝对路径形态（49 处） | 主机特定值不得进入纳入版本控制的文档 |
| `AGENTS.md` 中「本地 `<host-abs-path>`」式表述 | 同 `topology` 不变量；改用角色名（`DiffAgent2 新版 / 旧版`） |
| （若复核命中）任何密码/令牌/私钥字面量 | 硬约束 1；立即删除并上报，不登记进文档 |

> 说明：不删除任何方案条目、不删除公开仓库 URL；`doc/` 下方案**不新增**「已脱敏」注释桩。

## 7. 实施步骤（P0 单期）

### P0 — 标识替换 + 门禁复核

- 范围：§5 映射表全部行；`specs/` 与代码零改动。
- 行为不变式：替换后每条命令在 `<new-repo-root>` 语境下语义等价；方案结论、行号、验收项逐字不变（除路径字面量）。
- 步骤：
  1. 对 `doc/**` 三份 `done` 方案做替换（纯标识）；
  2. 对 `AGENTS.md` 三行绝对路径做替换（保留新旧库区分能力，用角色名 + `<…-repo-root>`）；
  3. 放行后对 `.trae/skills/github-pull/SKILL.md` 四行绝对路径做替换；
  4. 复核：检索命中集合应**恰好等于** §5 的「保留」集合；计数应为 18（未放行时按实际保留数记录）。
  5. 在总纲 §2.C 勾掉本项，并在附录登记执行日期与命中数（不写模式、不写内容）。
- 回退：`git checkout --` 还原文档（本期零代码、零契约，回退无副作用）。

## 8. 验收标准

- [ ] 检索（模式取自 station-host 本地区，占位 `<personal-id>` / `<host-abs-path>`）在纳入版本控制的
      `*.md` / `*.sh` / `.trae/skills/**` 上的命中集合 == §5「保留」集合（17 处公开仓库标识）。
- [ ] `AGENTS.md` 仍能明确区分「DiffAgent2 新版」与「DiffAgent2 旧版」（替换后逐句复核）。
- [ ] `github-issue` / `github-pull` 两份 SKILL 的默认仓库与命令仍可执行（保留项按 §5 未动）。
- [ ] `doc/**` 内不再出现任何 `<host-abs-path>` 形态路径；施工命令替换为 `<…-repo-root>` 后逐条可读。
- [ ] 零代码改动：`git diff --stat` 仅含 §5 列出的文档。
- [ ] 本方案文档自身零命中（建立「新文档从一开始合规」的先例）。

## 9. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 替换后命令失去可复跑性（占位未说明） | 执行者无法照抄 | §4 规则表给出 `REPO_ROOT=<new-repo-root>` 写法；文档上下文补一行「占位含义」 |
| 误删公开仓库标识 | `github-issue`/`github-pull` 失效、AGENTS issue 规则失效 | §5「保留」清单逐行锁定 + §8 复核项 |
| 三份 `done` 方案被质疑「历史记录不得改」 | 评审返工 | §4「历史文档处置裁决」给出理由：绝对路径是缺陷，机械替换不改结论 |
| `AGENTS.md` / `.trae/skills` 未放行导致 S0 半程 | 门禁 A4 无法判绿 | §4「放行边界裁决」：未放行只改 `doc/`，缺口在总纲登记为未完成项（非豁免） |
| 检索模式入库造成二次泄露 | 违反约束 2 | 模式不入库；本方案只用占位符；执行记录只写命中数 |

回滚路径：`git checkout -- <files>`（纯文档改动，无副作用）。

## 10. 修改点清单汇总

| 文件 | 动作 | 说明 |
|---|---|---|
| `AGENTS.md` | 修改 | L28/L39/L41 绝对路径 → `<new-repo-root>` / `<old-repo-root>`；其余保留 |
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-taskid-retirement-deps-migration.md` | 修改 | 20 处标识替换 |
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-core-inference-migration.md` | 修改 | 14 处标识替换 |
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-engine-narrow-core-trim.md` | 修改 | 8 处标识替换 |
| `.trae/skills/github-pull/SKILL.md` | 修改 | L24/L32/L34/L37 绝对路径替换（需放行） |
| `.trae/skills/github-issue/SKILL.md` | 不改 | 零命中主机路径 |
| `doc/l3-dispatcher-planner/iteration/design-dispatcher-privacy-gate-cleanup.md` | 新增 | 本方案 |

**登记**：`specs/tools/` 门禁脚本迁移后，A4 由脚本承担自动检查（不在本套内）。

## 11. 附录：执行记录

### 2026-09-12 执行（S0 置 done）

- **执行者**：SOLO Agent（主 Agent 直接执行；G-放行-1 已取得，用户放行全部范围含 `AGENTS.md` 与 `.trae/skills/`）。
- **本地准备（§7.0）**：快照 `/tmp/diffagent2-s0s1-snapshot-20260912-160659`（AGENTS.md、doc 三份 done 方案、specs/、.trae/skills）；环境判定：`rospy`/`yaml`/`numpy` 可导入（L2/L3 冒烟可用）、pytest 6.2.5 可用。
- **执行实测**：49 处主机绝对路径全部替换为 `<new-repo-root>` / `<old-repo-root>`（taskid 20、core-inference 14、narrow-core-trim 8、AGENTS.md 3、github-pull SKILL 4）；替换后检索 `<host-abs-path>` 形态（`/home/<personal-id>`）在 `AGENTS.md`、`doc/`、`specs/`、`.trae/skills/` 上零命中；保留集合 17 处公开服务标识（`zhywwyzh/DiffAgent2` 16 处 + `zhywwyzh/l3-uss-nav` 1 处示例仓主名）。本方案文档自身零命中。
- **验收逐条**：§8 六项全部通过；AGENTS.md 新旧版区分能力保持（`<new-repo-root>`/`<old-repo-root>` + 角色名）；`github-issue`/`github-pull` 保留项未动。
- **勘误（已回写正文）**：`github-issue/SKILL.md` 实测 8 处（原记 9）；公开服务标识合计 17（原记 18）；总命中 66（原记 67，§1/§2/§5/§7/§8 五处同步修正）；总纲 §2.C 计数 16→15、67→66 同步修正。
- **基线门禁（§8.3，当期范围=文档）**：A4 通过；`py_compile` 全量通过；pytest 基线：44 通过 / 6 失败（`test_rpc_plane_navigation.py`，为本期开工前既有失败，与 S0 零代码改动无关，登记由后续轮次覆盖 `rpc_plane` 改动时复核）；`test_connection_lease.py` 因主机缺 `zenoh` 模块无法收集（环境缺失，按 R9 回退记录，不判失败）。
- **工作区既有改动说明**：开工前工作区已存在非本期改动（`AGENTS.md` 新增「契约加载」节、`engine.py`、`tools/__init__.py`），属此前会话遗留、保留不动；`git diff --stat` 中出现但不计入本期。
- **未完成项与后续轮次**：`specs/tools/*` 迁移后 A4 自动化（已在 §10 登记）。

> 注：本附录曾于 2026-09-12 回写后被外部进程（Trae IDE 陈旧缓冲）回滚丢失，2026-09-13 依据会话记录重建，内容与首次回写一致。
