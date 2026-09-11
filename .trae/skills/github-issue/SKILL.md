---
name: "github-issue"
description: "向 GitHub 仓库（默认 https://github.com/zhywwyzh/DiffAgent2）创建 issue。当用户给出 GitHub 仓库地址、branch（可选）和 issue 内容，并要求把 issue 提交到该仓库时调用。"
---

# GitHub 创建 Issue（github-issue）

将用户给出的 issue 提交到指定的 GitHub 仓库，创建成功后返回 issue 链接。

## 默认发布地址

- 默认仓库：`https://github.com/zhywwyzh/DiffAgent2`（即 `zhywwyzh/DiffAgent2`）
- 已用 `gh` 登录（`gh auth status` 可验证），创建可直接使用
- GitHub 一律使用 `https://` 协议

## 仓库识别原则

判断目标仓库前，先区分两种概念：

- **仓库地址**：形如 `https://github.com/<owner>/<repo>` 的 URL，或
  `owner/repo` 的完整路径（含 `/`，可直接作 `-R` 参数）。只有这两种才算
  「明确指定了仓库」。
- **项目/需求名称**：单独的普通名词（如「l3-dispatcher-planner」
  「diff-dockers」），或「向 XX 项目提出需求」中的 XX，是 issue 内容的
  一部分，不是仓库地址。

**禁止为确定仓库而做任何查找**：不得用 `gh` 搜索仓库、调用 GitHub API
查询、`git ls-remote` 试探来解析用户提到的项目名。用户说「向 XX 项目
提出需求」时，直接使用默认仓库创建 issue，XX 仅作为内容写入 issue 描述。

## 默认仓库

**除非用户明确指定了仓库地址（URL 或 `owner/repo` 完整路径），否则一律
使用默认仓库，不解析、不查找。**

默认仓库信息：

- 仓库地址：`https://github.com/zhywwyzh/DiffAgent2`
- 仓库标识：`zhywwyzh/DiffAgent2`

其余任何情况（未提及仓库、只提项目/需求名称、含糊表述如「推到当前库」等）
都走默认仓库。

## 确定 branch

1. 若用户明确给出 branch，直接使用；
2. 若未给出，取该仓库的**默认分支**（default branch）：
   ```bash
   gh repo view zhywwyzh/DiffAgent2 --json defaultBranchRef -q .defaultBranchRef.name
   ```
   或：
   ```bash
   git ls-remote --symref https://github.com/<owner>/<repo>.git HEAD
   ```
   输出中 `ref: refs/heads/<branch> HEAD` 即为默认分支名。
3. issue 本身不带 branch 字段，将 branch 作为上下文写入 issue 描述，
   例如「关联分支：`<branch>`」。

## 创建 Issue 流程

1. 确定仓库：默认使用「默认仓库」；仅当用户明确给出仓库地址（URL 或
   `owner/repo`）时使用该地址。**不要为确定仓库做任何搜索**
2. 确定 branch（见「确定 branch」）
3. 使用 `gh` 创建 issue（非交互）：
   ```bash
   gh issue create -R zhywwyzh/DiffAgent2 \
     -t "<issue 标题>" \
     -b "<issue 描述>"
   ```
   - 描述较长或含多行时，直接用 `-b` 传多行文本（单引号包裹）；也可用
     `--body-file`，但文件**不要放在 `/tmp`**（沙箱下可能读不到），应放
     `$HOME` 或当前目录
   - 可选参数：`-a username`（指派）、`-l label`（标签）、`-m milestone`
     （里程碑）、`-p project`（项目）——仅在用户要求时使用
4. 验证：命令输出会给出创建的 issue 链接，返回给用户

## 描述格式建议

- 标题（title）：从用户给出的 issue 中提取，简洁概括
- 描述（body）：保留用户原始 issue 内容，可在末尾附上「关联分支：`<branch>`」
- 保持用户原意，**不要自行改写、删减或虚构内容**

## 注意事项

- GitHub 一律使用 `https://` 协议
- 除非用户明确给出仓库地址（URL 或 `owner/repo`），否则一律使用默认仓库
  `zhywwyzh/DiffAgent2`，且不要搜索/解析用户提到的项目名
- 所有 `gh issue create` 命令带 `-R zhywwyzh/DiffAgent2`，防止落到其他仓库
