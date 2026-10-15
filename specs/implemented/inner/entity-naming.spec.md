# 执行实体命名契约

Status: implemented
Contract-ID: topology/entity-naming
Parent: specs/implemented/topology.spec.md

## 范围与非目标

> 定义运维脚本的执行实体词汇。执行实体只回答一个问题：
> **这个脚本在哪里运行。**

## 术语与身份

### 1. 执行实体词汇

> 执行实体词汇；每个名字说明该类脚本运行在何处。

| 实体 | 平面 | 执行位置 | 典型脚本 |
|--------|-------|-----------------|-----------------|
| `station-host` | station | 操作者站点上的裸机 | 编排、spec-lint、k3s/kubectl 驱动、镜像仓库检查 |
| `drone-host` | drone | Jetson 上的裸机 | 部署、硬件探测、就地编译 |
| `drone-container` | drone | 设备上的容器内 | l0..l3 pod ctr-* 探测、pod 内抓取工具 |

边界：

- 站点是操作者主台：事实来源、仓库撰写、编排。`image-registry` 与
  `gitlab-internal` 是服务角色（镜像仓库服务器 / 内部 gitlab）——处于这些
  角色的机器不是执行实体，其上脚本不带实体前缀。
- `host` = 裸机；`container` = k3s/docker 容器内。
- **双模式脚本**（如制品新鲜度检查：站点聚合默认、设备 `--local`）：
  文件名 + 头取主要调用实体；头里记录变体。
- **双端工具**（两个平面上运行方式相同，如 manifest 渲染）：
  `# Entity: shared`，无文件名前缀。

## 输入、输出与配置

Entity 与 Invoked 是脚本头字段，含义与允许实体见 §1、§2；本契约不定义业务载荷或机器配置值。

## 行为规则

### 2. 脚本标记规则

> 脚本在头注释里声明其实体，顶层目录也带实体文件名前缀。

1. 每个可执行运维脚本在头里声明 `# Entity: <entity>` 与
   `# Invoked: <how>`（如 `# Invoked: directly by the operator`、
   `# Invoked: locally or via SSH`）。`shared` 工具声明 `# Entity: shared`。
2. 顶层脚本目录（`scripts/`、`specs/tools/`、`deployment/`）
   以实体为前缀命名可执行文件名：`<entity>-<name>.sh`——一眼看出它在哪里运行。
3. 头约定——实体词汇（§1）加上 `# Entity:` / `# Invoked:`——只归本 spec
   所有，并在每个纳入版本控制的公开脚本中强制（顶层 `scripts/`、
   `specs/tools/`、`deployment/`、skill `scripts/`）。
   主机本地运维脚本遵循同一约定。
4. 容器侧 bringup 脚本（`bringup/*/scripts/ctr-*.sh`）暂保留其
   功能导向命名；目标词汇是 `drone-container-*`（§3，待迁批次）。

### 3. 保留标记边界

> 表里将每个待迁移实体标记映射到其后继。

| 旧标记 | 后继实体 | 保留条件 |
|----------------|-----------|--------|
| `ctr-real`（bringup 探测） | `drone-container` | 待迁批次 |

## 失败、取消与资源生命周期

命名失败属于静态契约缺陷；本契约不获取运行资源，脚本自身的取消和释放由其能力契约定义。

## 归属与依赖

实体词汇由本叶唯一拥有，稳定身份与隐私边界归父根 topology。

### 变更关联

```contract-links
{
  "implementation": [
    "scripts/**",
    "deployment/tools/**",
    "deployment/k3s/**/*.sh",
    "specs/tools/*.py",
    "drone_projects/l3-dispatcher-planner/tools/**",
    "drone_projects/l3-dispatcher-planner/bringup/**/scripts/**"
  ],
  "depends_on": [
    "topology"
  ]
}
```

## 条款检查判据

### 4. 约束判据

> 命名规则由本 spec 强制；具体 lint 门禁尚未迁移到本仓库。

执行实体的头标记与文件名前缀规则是硬性契约：每个纳入版本控制的顶层
运维脚本必须带 `# Entity:` 头，`ctr-*` 标记在 待迁批次 落地前不强制
改名为 `drone-container-*`。门禁脚本迁移后由它承担自动检查。

检查执行与证据记录遵循 `specs/README.md` 的统一许可边界；本文件不记录通过结论。
