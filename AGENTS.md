# Agent 操作档案 — Diff-Agent2.0

> 给在本仓库工作的任何 agent 的约束与指引：这个仓库是什么、
> 哪些规则是硬性的、每个主题的权威归属在哪里。事实和契约放在
> 各自的归属文件里，本文件只做约束与指引，不重复它们。

## 当前迭代焦点

> 默认编辑目标是 `l3-dispatcher-planner/`（本仓库根下的内置子树，
> 由本仓库跟踪）；迭代分支建在本仓库（GitHub `zhywwyzh/DiffAgent2`）上。

- **默认目标：`l3-dispatcher-planner/`** — 所有修改请求（功能、修复、
  重构、测试、文档）默认落到这棵树，即使请求没有点名路径。
- **迭代分支建在本仓库** — 迭代分支（如 `0907-vla-iteration`）建在
  GitHub `zhywwyzh/DiffAgent2` 上，并承载内置的 l3 改动；
  绝不在嵌套的项目检出目录里建分支。
- **显式覆盖才改别处** — 其他树（`.trae/skills/`、本文件等）只在
  请求明确点名时才改；含糊请求一律落到 `l3-dispatcher-planner/`，
  不跨树扩散。

## 这个仓库是什么

> 编排仓库：统一 spec 注册表 `specs/`、agent 技能 `.trae/skills/`、
> 以及内置的 `l3-dispatcher-planner` 子树。当前只迁移了技能与
> 编排定位的说法，具体内容暂不迁移。

- 本仓库（GitHub `zhywwyzh/DiffAgent2`，本地
  `<new-repo-root>`）是一个**编排仓库**：
  统一 spec 注册表 `specs/`、agent 技能 `.trae/skills/`，以及内置
  的 `l3-dispatcher-planner` 子树。
- 原 diff-dockers 编排仓库中的 `specs/`、`docker_registry/`、
  `drone_projects/auto_deployer/` 等实际内容**暂不迁移**，这里只保留
  “编排仓库”这一定位说法。

## 新旧版本命名

> 严格区分两个仓库，避免在文档与交流中混淆。

- **本仓库**（`<new-repo-root>`，GitHub
  `zhywwyzh/DiffAgent2`）= **DiffAgent2 新版**。
- **另一个仓库**（`<old-repo-root>`）=
  **DiffAgent2 旧版**。

DiffAgent2 旧版的实际路径以仓库根目录 `.local.env` 中的 `OLD_REPO_ROOT`
为唯一来源。研究或迁移前必须读取该配置；未配置时询问用户，禁止根据
目录名猜测。实际路径只保存在被 Git 忽略的 `.local.env` 中，不写入纳入
版本控制的文档。

在文档、spec、issue 与对话中提到二者时，一律用“DiffAgent2 新版 /
DiffAgent2 旧版”称呼，不混用路径或简称。

## 权威顺序

> 当本文件与 spec 冲突时，spec 优先，并修正本文件。

`specs/` > 本文件。冲突时 spec 优先，并修正本文件。`specs/README.md`
是 spec 注册表及其规则。

## 契约加载

> 本文件不重复契约内容，只声明读取入口。

### 契约编写强制入口

- 任何 agent 修改实现、配置、消息、接口或目录，以及新增、修改、移动或归档契约前，**必须先完整读取**
  [specs/README.md](specs/README.md)，并执行其中的 **Agent 执行约束**。
- 生命周期、header、正文模板、条款写法、变更流程和检查规则只归该入口所有；
  **不得仅凭旧文件样式编辑，不得在其它位置另建规则副本或擅自放宽要求**。
- 门禁执行遵循本文件硬性约束 §9 的许可边界；不得把文件已修改、门禁未运行或
  检查失败报告为合规完成。实际检查范围和结果必须随交付说明。
- 即使使用者只要求修改代码，也必须按 README 的 A6 加载实现变更同步契约，
  修改前建立任务基线，在方案记录每个配套契约的“已同步／核对不变／待同步”及证据。
  同步门禁未通过时不得宣称任务配套契约已处理完成，不以默认结构检查替代同步检查。

### 领域契约读取

- **l3 相关任务**（任务分发 / 下行执行 / 运动规划）：开工前先读
  `specs/implemented/l3-dispatcher.spec.md`，并按其 `## Inner contracts`
  表读完列出的全部叶契约。
- **其他领域任务**：先列 `specs/implemented/` 下的根契约，按领域选读；
  根契约的 `## Inner contracts` 表是其叶契约的权威清单。

### l3 待迁依赖读取入口

- 涉及 dispatcher 收紧、字段/参数删除、旧版 skill 迁移、记录服务、返航、
  动作武装、VLA 调试或急停悬停时，开工前还须读取
  [rest 索引](doc/l3-dispatcher-planner/rest/README.md)，并读完
  [保留项台账](doc/l3-dispatcher-planner/rest/dispatcher-deferred-dependencies.md)
  中对应条目的触发条件、旧版调用链、接入建议、验收和可删除条件。
- 新版没有当前消费者，不等于已无用途；必须结合 DiffAgent2 旧版的 skill
  与共享服务判断。用户明确暂时保留的项不得仅按新版引用计数裁掉。
- `rest/` 是迁移过程资料，不替代 `specs/`。接入、迁移归属或删除相关项时，
  在同一改动内更新台账及索引，附实现/测试证据和剩余触发条件；不得只留
  “以后处理”，也不得把保留字段视为生产能力已实现。

## 硬性约束

> 本仓库交付/共享时的不可协商约束。

1. **文档不写主机本地凭据与机器特定值**：`*.md`（spec、docs、本文件）只写
   角色名（`specs/implemented/inner/entity-naming.spec.md` 的实体词汇）；密码、
   令牌、私钥，以及主机绝对路径、个人用户名等**机器特定值**，绝不进入纳入
   版本控制的文件，只放在被忽略的主机本地区（如 `.local.env`）。**公开服务
   标识**——公开仓库 URL 与其仓主名、服务角色名——不属凭据，可入库。
2. **提交前隐私门禁**：每次提交/推送前，对纳入版本控制的文件跑隐私
   检索（个人用户名/密码/令牌），必须无匹配。检索模式维护在主机本地，
   不写入纳入版本控制的文件。
3. **spec 优先、门禁绿**：改动 spec/本文件时，检查入口及执行要求以
   `specs/README.md` 为准；当前入口为 `python3 specs/tools/station-host-spec-lint.py`。
   执行须符合第 9 条许可边界，不引用尚未迁移的脚本冒充已完成门禁。
4. **子模块/内置子树纪律**：子模块或内置子树的改动不与父仓库一起提交，
   需显式指令；更新父仓库的 gitlink 是单独的、显式请求的动作。
5. **禁止项目本地 spec**：spec 只能放在 `specs/` 下，不散落在项目
   仓库或其 `docs/` 里。
6. **禁止硬编码远端凭据**：脚本通过 git 凭据存储 / 环境变量解析远端，
   不硬编码密码、令牌或带凭据的远端地址。
7. **禁止预提交钩子**：提交用 `git commit --no-verify`；门禁显式手动跑，
   不安装、不重新启用钩子。
8. **文档一律简体中文**：本仓库所有文档（`*.md`、spec、本文件）一律用
   简体中文撰写；仅代码标识符、路径、URL 等技术标识保持原样。
9. **验收测试统一声明**：除非使用者明确许可，否则跳过验收测试工作——不运行
   测试、不做验证性验收，也不预先读取 test 相关文档（测试文件、测试说明等）。
   本声明跨 `specs/`、`doc/` 与本文件统一适用；与 spec 的验收/门禁条款冲突
   时，以本声明为准。

## Issues

> 本仓库的 issue 一律建在 GitHub `zhywwyzh/DiffAgent2` 上。

所有 issue（l3-dispatcher-planner、skills 等）都建在当前 GitHub 仓库：
`gh issue create -R zhywwyzh/DiffAgent2`。没有仓库限定词的 “issue”
即指本仓库。

## 原则

> 操作默认值：先重启再诊断、spec 先行、用证据判定。

- **先重启再诊断**：异常先干净重启，等 5 秒复查，只有复现才深入挖日志。
- **spec → 在 owner 仓库执行 → 监控**：跨实体任务先在 `specs/` 落地
  契约，再在 owner 仓库执行，用测试/运行时证据判定，而非只看命令退出码。

## 代码优化工作流

> 硬约束：所有代码修改「先方案、后执行」；方案按工作空间落盘
> `doc/<workspace>/iteration/`（当前 l3 →
> `doc/l3-dispatcher-planner/iteration/`），格式遵循
> `doc/l3-dispatcher-planner/iteration/_TEMPLATE.md`。以下六条为
> 不可协商项。

1. **先方案后改码**：任何代码修改相关工作，必须先产出对应方案，再严格
   依据方案修改。唯一例外：用户明确指示「可直接调整代码」。
2. **方案落盘地址**：用户要求将方案生成到本地时，默认按工作空间落到
   `doc/<workspace>/iteration/`（当前 l3 → `doc/l3-dispatcher-planner/iteration/`）。
3. **统一方案格式**：方案必须遵循对应工作空间的 `_TEMPLATE.md`
   （§0–§10；当前 l3 → `doc/l3-dispatcher-planner/iteration/_TEMPLATE.md`）。
   可参考 `doc/` 下既有文档，但最终以模板为准。
4. **目录架构与命名规范是优化对象**：目录架构不统一、文件命名无规范的
   问题，优化须把「统一目录架构 + 统一命名规范」纳入方案。
5. **禁止转接器（anti-adapter）**：新旧接口不统一时，不允许新设计一个
   转接器来桥接新旧接口，除非用户明确允许。
6. **过期必删（no legacy shim）**：被新功能替代的旧功能必须直接删除，
   不得保留为转接口，也不得仅注释掉，除非用户明确要求保留老接口。
