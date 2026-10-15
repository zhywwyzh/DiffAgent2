# 工作区角色目录与项目归属

Status: implemented
Contract-ID: development-workflow/workspace-layout
Parent: specs/implemented/development-workflow.spec.md

## 范围与非目标

约束 DiffAgent2 新版根目录的项目分类、部署归属与路径解析；不改变算法、任务协议、独立仓库远端或运行时安全要求。

## 术语与身份

- **WL1 角色目录**：drone_projects 放机端项目，station_projects 放站端应用，simulation_projects 放仿真项目。角色表达职责，不由层级编号代替。
- **WL2 版本归属**：drone_projects/l3-dispatcher-planner 是父仓库跟踪的内置子树；station_projects/l4-agent 与 simulation_projects/l2-simulator-amd64 是被父仓库忽略的独立检出。

## 输入、输出与配置

- **WL3 根入口**：根 Makefile 必须调用 deployment/tools 的全栈入口；根 .local.env 仍是被忽略的主机配置来源。独立检出默认路径按 WL2，显式外部覆盖必须保留。
- **WL4 路径定位**：全栈工具必须从 deployment 定位编排根与角色项目，不得假设 L3、L2、L4 同级。构建与运行容器路径由 runtime 叶声明，不从主机目录名猜测。

## 行为规则

- **WL5 唯一归属**：全栈启停、镜像和远端投放工具归 deployment/tools；k3s 装配归 deployment/k3s；装配制品归 deployment/.artifacts。L3 的项目构建脚本、ROS launch、算法参数及包保留在机端项目。
- **WL6 同轮迁移**：目录移动必须同步 Makefile、配置默认值、契约 implementation 绑定、主机根解析、容器挂载、IDE 项目路径与文档导航。不得保留旧路径软链接、转发脚本或第二份源码。
- **WL7 资料位置**：spec 只归根 specs；工作空间方案与台账保留 doc/l3-dispatcher-planner。冻结历史正文按 specs/README.md D1–D2 维护，不改写其当时的源码事实。

## 失败、取消与资源生命周期

- **WL8 路径制品**：旧绝对路径的虚拟环境与编译记录不得冒充可复用制品。迁移可以保留原始缓存和日志，但必须通过对应入口重新准备。工作区资源 owner 仍从同一编排根计算，不因项目分组改变身份。
- **WL9 仓库纪律**：移动独立检出不得把其源码、Git 元数据或凭据加入父仓库；不得自动改变其远端、提交或 gitlink。
- **WL10 IDE 仓库发现**：共享工作区设置必须使用仓库相对路径显式登记角色目录下的独立检出，使 Git 仓库发现不依赖默认扫描深度。L3 继续归父仓库，不得为 IDE 显示另建嵌套仓库；源码定位不得保留迁移前路径或机器绝对路径。

## 归属与依赖

本叶唯一拥有工作区顶层布局，dispatcher 内部目录归 l3-dispatcher/package-layout；部署行为归 runtime，执行实体命名归 topology/entity-naming。

```contract-links
{
  "implementation": [
    "drone_projects/**",
    "station_projects/l4-agent/**",
    "simulation_projects/l2-simulator-amd64/**",
    "deployment/**",
    "Makefile",
    ".gitignore",
    ".vscode/settings.json",
    "AGENTS.md",
    "CODEBUDDY.md",
    "README.md",
    "doc/code-atlas/**"
  ],
  "depends_on": ["development-workflow", "topology/entity-naming"]
}
```

## 条款检查判据

WL-C1：核对角色路径、版本归属与忽略规则；WL-C2：核对 Makefile、工具根定位、挂载及契约绑定；WL-C3：核对旧入口移除、导航闭合及制品重新准备说明；WL-C4：核对 IDE 独立仓库发现路径及源码定位与角色目录一致。
检查许可及证据记录遵循 specs/README.md，不以静态通过宣称运行验收。
