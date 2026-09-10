---
name: "gitlab-issue"
description: "向私有 GitLab（默认 http://localhost:8929/big_brain/diff-dockers.git）推送/创建 issue。当用户给出 gitlab 仓库地址、branch（可选）和 issue 内容并要求把 issue 推送到该仓库时调用。"
---

# GitLab 推送 Issue（gitlab-issue）

将用户给出的 issue 推送到指定的私有 GitLab 仓库，创建成功后返回 issue 链接。

## 默认发布地址

- 默认发布地址（用户视角）：`http://localhost:8929/big_brain/diff-dockers.git`
- 该地址中的 `localhost` 即指可达主机 `129.211.229.251`，glab 实际使用 `http://129.211.229.251:8929`
- 已用 `glab` 以账号 `zhywwyzh` 登录，token 有效，创建可直接使用
- 该实例为**纯 HTTP**（非 HTTPS），所有操作一律使用 `http://` 协议，不要改成 `https://`
- **所有 glab 命令必须显式指定本实例**，否则可能落到默认 host（如 `gitlab.com`）而报 404：
  每条命令前加 `GITLAB_HOST=129.211.229.251:8929`，或在会话内先 `export GITLAB_HOST=129.211.229.251:8929`
- 执行前建议先验证连通：`GITLAB_HOST=129.211.229.251:8929 glab auth status`

## URL 主机替换规则

用户给出的仓库 URL 中，**仅当主机是 `localhost:8929`（或 `localhost`）时**，替换为默认主机 `129.211.229.251:8929`。

- 示例：用户给 `http://localhost:8929/big_brain/l3-uss-nav.git`
  → 实际使用 `http://129.211.229.251:8929/big_brain/l3-uss-nav.git`
- 若用户给出其他明确主机（如 `192.168.200.101:8929`），**保持原样**，不替换。

## 仓库识别原则

判断目标仓库前，先区分两种概念：

- **仓库地址**：形如 `http://<host>/<group>/<repo>.git` 的 URL，或 `GROUP/REPO` 的完整路径（含 `/`，可直接作 `-R` 参数）。只有这两种才算「明确指定了仓库」。
- **项目/需求名称**：单独的普通名词（如「lx-real-k3s」「diff-dockers」），或「向 XX 项目提出需求」中的 XX，是 **issue 内容的一部分**，不是仓库地址。

**禁止为确定仓库而做任何查找**：不得用 `glab` 搜索项目、调用 GitLab API 查询、`git ls-remote` 试探来解析用户提到的项目名。用户说「向 XX 项目提出需求」时，直接使用默认仓库创建 issue，XX 仅作为内容写入 issue 描述。

## 默认仓库

**除非用户明确指定了仓库地址（URL 或 `GROUP/REPO` 完整路径），否则一律使用默认仓库，不解析、不查找。**

默认仓库信息：

- 用户视角地址：`http://localhost:8929/big_brain/diff-dockers.git`
- 按「URL 主机替换规则」归一化后：`http://129.211.229.251:8929/big_brain/diff-dockers.git`
- 仓库标识：`big_brain/diff-dockers`

其余任何情况（未提及仓库、只提项目/需求名称、含糊表述如「推到当前库」等）都走默认仓库。

## 解析仓库标识

从归一化后的 URL 提取 `OWNER/REPO`（可能为 `GROUP/REPO` 或 `GROUP/NAMESPACE/REPO`），作为 `-R` 参数：

- `http://129.211.229.251:8929/big_brain/l3-uss-nav.git` → `big_brain/l3-uss-nav`
- 取路径最后一段并去掉 `.git` 后缀得到 repo 名，路径其余部分为 group/namespace

为消除多实例歧义，也可直接将**完整归一化 URL** 传给 `-R`（glab 支持完整 URL / Git URL）。

## 确定 branch

1. 若用户明确给出 branch，直接使用；
2. 若未给出，取该仓库的**默认分支**（default branch）：
   ```bash
   git ls-remote --symref <normalized-url> HEAD
   ```
   输出中 `ref: refs/heads/<branch> HEAD` 即为默认分支名。
3. issue 本身不带 branch 字段，将 branch 作为上下文写入 issue 描述，例如「关联分支：`<branch>`」。

## 推送 Issue 流程

1. 确定仓库 URL：**默认使用「默认仓库」**；仅当用户明确给出仓库地址（URL 或 `GROUP/REPO`）时，才按「URL 主机替换规则」归一化使用该地址。**不要为确定仓库做任何搜索**
2. 解析仓库标识 `OWNER/REPO`
3. 确定 branch（见「确定 branch」）
4. 使用 `glab` 创建 issue（非交互，务必带 `GITLAB_HOST`）：
   ```bash
   GITLAB_HOST=129.211.229.251:8929 glab issue create -R <OWNER/REPO> \
     -t "<issue 标题>" \
     -d "<issue 描述>" \
     --no-editor -y
   ```
   - 描述较长或含多行时，直接用 `-d` 传多行文本（单引号包裹）；也可用 `--description-file`，但文件**不要放在 `/tmp`**（snap 沙箱下读不到），应放 `$HOME` 或当前目录；若报 `Failed to read description file`，改用 `-d` 重试
   - 可选参数：`-l label`（标签）、`-a username`（指派）、`-m milestone`（里程碑）、`--confidential`（保密）——仅在用户要求时使用
5. 验证：命令输出会给出创建的 issue 链接（若显示 `localhost:8929`，按「URL 主机替换规则」归一化后返回给用户）

## 描述格式建议

- 标题（title）：从用户给出的 issue 中提取，简洁概括
- 描述（description）：保留用户原始 issue 内容，可在末尾附上「关联分支：`<branch>`」
- 保持用户原意，**不要自行改写、删减或虚构内容**

## 注意事项

- 该 GitLab 是纯 HTTP 服务，URL 一律 `http://`，不要改成 `https://`
- 不要替换用户明确给出的非 localhost 主机
- 除非用户明确给出仓库地址（URL 或 `GROUP/REPO`），否则一律使用默认仓库 `big_brain/diff-dockers`，且不要搜索/解析用户提到的项目名
- 所有 glab 命令带 `GITLAB_HOST=129.211.229.251:8929`，防止落到 gitlab.com 报 404
- 若 `-R OWNER/REPO` 解析失败或指向了错误的实例，改用完整归一化 URL 重试
