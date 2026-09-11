# 开发工作流契约

Status: implemented
Contract-ID: development-workflow

> 拥有整个工作区内的源码撰写与仓库工作流。它定义客观的 Git 与
> worktree 边界，而不维护人类或 agent 执行角色的中央登记表。

## 不变量

> 源码改动发生在拥有该源码的仓库里，自动化在运行时解析 Git 事实而非猜测它们。

- 本地检出是撰写源码的事实来源。
- 自动化在运行时解析远端及其默认分支，不硬编码凭据。
- 每个 issue 隔离一个任务 worktree 与分支；交付证据是一次提交加上该
  仓库的检查结果。

## Inner contracts

> 叶契约承载仓库特定的机制与开发实践。

| Contract | Authority |
|----------|-----------|
| `specs/implemented/inner/l3-coding-style.spec.md` | l3 源码约定 |

## 边界

> 运行时部署与产品行为不是开发工作流关心的事。

构建产物、栈变更、飞行语义与站点协议归各自的根契约所有。
