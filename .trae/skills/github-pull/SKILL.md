---
name: "github-pull"
description: "从 GitHub（默认 https://github.com/zhywwyzh/DiffAgent2）拉取/克隆代码库，并按 Diff-Agent2.0 分工作区规则决定 clone 位置。当用户要求拉取/克隆某个 GitHub 仓库、给出 GitHub 仓库 URL、或要求在当前目录制作分工作区时调用。"
---

# GitHub 拉取代码（github-pull）

从 GitHub 拉取代码，并根据当前工作目录决定 clone 的目标位置。

## 默认 GitHub 地址

- 默认仓库：`https://github.com/zhywwyzh/DiffAgent2`
- GitHub 一律使用 `https://` 协议

## 确定目标位置（分工作区规则）

拉取前先判断当前所在目录（pwd），按以下规则决定 clone 到哪。

### 情况 A：绑定到 Diff-Agent2.0 分工作区

满足以下任一条件时，将仓库 clone 到 Diff-Agent2.0 下的子目录，并绑定到
多根工作区：

1. 当前目录是 `Diff-Agent2.0` 本身（`<new-repo-root>`）；
2. 当前目录已经是 Diff-Agent2.0 的一个分工作区（即在 Diff-Agent2.0 的子目录内）；
3. 用户明确要求“在当前目录制作分工作区”或“绑定到分工作区”。

具体操作：

1. 从 URL 推导仓库名：取路径最后一段并去掉 `.git` 后缀
   - `zhywwyzh/l3-uss-nav.git` → `l3-uss-nav`
2. clone 到 `<new-repo-root>/<repo-name>/`
   ```bash
   git clone https://github.com/<owner>/<repo> <new-repo-root>/<repo-name>
   ```
3. 更新多根工作区文件
   `<new-repo-root>/Diff-Agent2.0.code-workspace`：
   - 在 `folders` 数组末尾追加 `{ "name": "<repo-name>", "path": "<repo-name>" }`
   - 若该仓库名已在 `folders` 中则跳过，避免重复
   - 保持 JSON 合法（注意逗号与引号）
4. clone 完成后提示用户重载窗口使新分工作区生效

### 情况 B：其他任意目录（默认）

不满足情况 A 的条件时，按标准 `git clone` 行为，clone 到**当前目录**下：

```bash
git clone https://github.com/<owner>/<repo>
```

### 情况 C：用户显式指定目标目录

若用户明确指定 clone 目标路径，以用户指定为准，跳过以上规则。

## 拉取流程

1. 判定目标位置（见“确定目标位置”）
2. 执行 `git clone`
   - 若目标目录已存在且是 git 仓库，向用户说明情况并选择：更新（`git pull`）
     或另换目录
3. 验证：进入克隆目录执行 `git status`、`git remote -v`，确认远端为正确的
   GitHub 地址且仓库正常

## 注意事项

- GitHub 一律使用 `https://` 协议
- 仓库地址形如 `https://github.com/<owner>/<repo>.git`
- 修改 `Diff-Agent2.0.code-workspace` 时必须保证 JSON 语法正确
