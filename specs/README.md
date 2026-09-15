# specs — 统一 spec 注册表

> 系统根契约与业务/实现叶契约的唯一权威来源。目录树加上每个叶契约的
> `Parent:` 头共同构成清单。事实与契约放在各自的归属文件里，本文件只做
> 规则与指引，不重复它们。

## 生命周期布局

> 每个 spec 恰好位于一个生命周期目录；其路径就是它的状态。

```text
specs/
├── README.md         本文件（只写规则，不做逐条索引）
├── implemented/      已采纳记录——唯一的规范性文件
│   ├── *.spec.md                      系统根契约（至多十个）
│   ├── inner/*.spec.md                业务/实现叶契约
│   ├── architecture/yyyy-mm-dd-*.md   结构性决策
│   └── process/yyyy-mm-dd-*.md        工作流/工具决策
├── proposed/         评审中；尚未采纳（或仅部分执行）
│   └── inner/                         叶契约提案
├── rejected/         被否决的提案，仅作为护栏保留
├── archived/         冻结的护栏——绝不再是权威
└── tools/            纳入版本控制的门禁引擎（尚未迁移）
```

> **生命周期目录按需创建**：未被使用的目录（如尚无决策记录的
> `implemented/{architecture,process}/`、空的 `proposed/` / `rejected/` /
> `archived/`）**不预建空目录、不预置占位文件**；首个记录落入时随该改动创建。
> 过程方案留在 `doc/` 下，不占 `specs/` 的权威。

## 根契约与叶契约层级

> 顶层文件是稳定的系统边界；所有业务、协议、实现与仓库细节都放在
> `inner/` 下，无论有多少个仓库实现它。

- **根契约** — `implemented/*.spec.md`。一个根契约拥有一个宽泛的系统
  领域、其不变量、边界与子契约清单。完整根集合最多十个物理文件，每个
  根契约最多 400 行。
- **叶契约** — `implemented/inner/*.spec.md`。一个叶契约拥有一个聚焦的
  行为或机制；它可以绑定一个或多个仓库，仓库数量不改变其层级。
- **决策记录** — `{architecture,process}/yyyy-mm-dd-*.md`。决策记录解释
  结构为何变化，不占用根预算。

每个现行契约在 `Status:` 下方声明 `Contract-ID:`。根 ID 是一个
kebab-case 段；叶 ID 是 `<root-id>/<leaf-id>`，并在 `Parent:` 里声明精确
的根路径。父根在 `## Inner contracts` 里列出每个已实现的叶路径。

分类测试：**「删除详细条款后是否仍留下稳定的系统边界与子契约映射？」**
答“是”即根。负载 schema、API 方法、状态机、runbook、实现表、仓库工作流
与产品行为都是叶或非 spec 文档。

## 两种记录，同一生命周期

> `*.spec.md` = 现行契约，与已交付内容保持同步；
> 带日期的 `{architecture,process}/` 文件 = 冻结的决策记录。

- **`<area>-<name>.spec.md`** — 现行契约。与真实交付内容保持一致：当
  代码、配置或名称变动时，正文在同一改动中更新。取代/负面事实只保留
  一行指针，绝不写叙述。
- **`{architecture,process}/yyyy-mm-dd-topic.md`** — 冻结的结构性决策
  （“为什么”与“放弃了什么”）。正文不再维护：对决策的推翻或修订是一条
  新记录，两条记录之间用 `Supersedes` / `Superseded-by` 交叉链接。

spec 承载详细的、可验证的契约；决策记录承载它由此长出的结构性理由。

## 命名与 header 规范

- **spec 命名**：根用 `<domain>.spec.md`；叶在 `inner/` 下保留聚焦的
  `<area>-<name>.spec.md` 文件名。不设其它 spec 子树。
- **header**：每个文件的第 3 行（`# Title` + 空行之后）是
  `Status: implemented | proposed | rejected — <why>`，且必须与所在目录
  一致。`implemented/` 下用 `Status: implemented`。
- **叶契约 header 骨架**：

```text
# Title

Status: implemented
Contract-ID: <root>/<leaf>
Parent: specs/implemented/<root>.spec.md
```

## 规则

> 以下规则违反即缺陷。

1. **每个 spec 一个权威** — `specs/` 下这份是唯一可编辑副本。别处不得
   出现镜像或“权威项目副本”头。
2. **不得重建项目本地 spec** — 在 `l*` 仓库（或其 `docs/`）里碰过或
   重新引入的 spec 是缺陷；先搬到这里。根/叶层级决定目录，而非实现仓库
   数量。
3. **实现不得分叉** — 当代码与 spec 冲突时，修实现，永不改 spec。契约
   变更先落在这里。
4. **生命周期按记录粒度为整** — 整条记录在生命周期目录间移动；片段走
   处置流程，绝不变成人为的 archived 或 rejected 记录。
5. **现行契约只含当前内容** — 陈旧事实、重复归属与迁移叙述在同一改动
   中移除，同时记录历史并修复活跃入链。

> 门禁脚本（`specs/tools/spec-lint.sh`、`station-host-spec-judge.py`、
> `station-host-doc-lint.sh` 等）尚未迁移到本仓库；迁移前不引用它们作为
> 强制门禁，也不在其它文件里凭空引用其规则。
