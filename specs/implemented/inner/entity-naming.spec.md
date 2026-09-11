# Entity Naming Spec

Status: implemented
Contract-ID: topology/entity-naming
Parent: specs/implemented/topology.spec.md

> 定义运维脚本的执行实体词汇。执行实体只回答一个问题：
> **这个脚本在哪里运行。**

## 1. Entity vocabulary

> 执行实体词汇；每个名字说明该类脚本运行在何处。

| Entity | Plane | Execution place | Typical scripts |
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

## 2. Script marking rules

> 脚本在头注释里声明其实体，顶层目录也带实体文件名前缀。

1. 每个可执行运维脚本在头里声明 `# Entity: <entity>` 与
   `# Invoked: <how>`（如 `# Invoked: directly by the operator`、
   `# Invoked: locally or via SSH`）。`shared` 工具声明 `# Entity: shared`。
2. 顶层脚本目录（`scripts/`、`specs/tools/`、`drone_projects/auto_deployer/`）
   以实体为前缀命名可执行文件名：`<entity>-<name>.sh`——一眼看出它在哪里运行。
3. 头约定——实体词汇（§1）加上 `# Entity:` / `# Invoked:`——只归本 spec
   所有，并在每个纳入版本控制的公开脚本中强制（顶层 `scripts/`、
   `specs/tools/`、`drone_projects/auto_deployer/`、skill `scripts/`）。
   主机本地运维脚本遵循同一约定。
4. 容器侧 bringup 脚本（`bringup/*/scripts/ctr-*.sh`）暂保留其
   功能导向命名；目标词汇是 `drone-container-*`（§3，deferred batch）。

## 3. Pending marker migration

> 表里将每个待迁移实体标记映射到其后继。

| Retired marker | Successor | Status |
|----------------|-----------|--------|
| `ctr-real`（bringup 探测） | `drone-container` | deferred batch |

## 4. Enforcement

> 命名规则由本 spec 强制；具体 lint 门禁尚未迁移到本仓库。

执行实体的头标记与文件名前缀规则是硬性契约：每个纳入版本控制的顶层
运维脚本必须带 `# Entity:` 头，`ctr-*` 标记在 deferred batch 落地前不强制
改名为 `drone-container-*`。门禁脚本迁移后由它承担自动检查。
