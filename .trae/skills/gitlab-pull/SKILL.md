---
name: "gitlab-pull"
description: "从私有 GitLab（默认 http://129.211.229.251:8929）拉取/克隆代码库，并按 Diff-Agent2 分工作区规则决定 clone 位置。当用户要求拉取/克隆某个 gitlab 仓库、给出 gitlab 仓库 URL、或要求在当前目录制作分工作区时调用。"
---

# GitLab 拉取代码（gitlab-pull）

从私有 GitLab 实例拉取代码，并根据当前工作目录决定 clone 的目标位置。

## 默认 GitLab 地址

- 默认主机：`http://129.211.229.251:8929`
- 已用 `glab` 以账号 `zhywwyzh` 登录，token 有效，拉取可直接使用
- 该实例为**纯 HTTP**（非 HTTPS），所有拉取/克隆一律使用 `http://` 协议，不要改成 `https://`

## URL 主机替换规则

用户给出的仓库 URL 中，**仅当主机是 `localhost:8929`（或 `localhost`）时**，替换为默认主机 `129.211.229.251:8929`。

- 示例：用户给 `http://localhost:8929/big_brain/l3-uss-nav.git`
  → 实际拉取 `http://129.211.229.251:8929/big_brain/l3-uss-nav.git`
- 若用户给出其他明确主机（如 `192.168.200.101:8929`），**保持原样**，不替换。

## 确定目标位置（分工作区规则）

拉取前先判断当前所在目录（pwd），按以下规则决定 clone 到哪。

### 情况 A：绑定到 Diff-Agent2 分工作区

满足以下任一条件时，将仓库 clone 到 Diff-Agent2 下的子目录，并绑定到多根工作区：

1. 当前目录是 `Diff-Agent2` 本身（`/home/zhywwyzh/workspace/Diff-Agent2`）；
2. 当前目录已经是 Diff-Agent2 的一个分工作区（即在 Diff-Agent2 的子目录内，如 `Diff-Agent2/l4-agent`）；
3. 用户明确要求“在当前目录制作分工作区”或“绑定到分工作区”。

具体操作：

1. 从 URL 推导仓库名：取路径最后一段并去掉 `.git` 后缀
   - `big_brain/l3-uss-nav.git` → `l3-uss-nav`
   - `big_brain/sub/xxx.git` → `xxx`
2. clone 到 `/home/zhywwyzh/workspace/Diff-Agent2/<repo-name>/`
   ```bash
   git clone <normalized-url> /home/zhywwyzh/workspace/Diff-Agent2/<repo-name>
   ```
3. 更新多根工作区文件 `/home/zhywwyzh/workspace/Diff-Agent2/Diff-Agent2.code-workspace`：
   - 在 `folders` 数组末尾追加 `{ "name": "<repo-name>", "path": "<repo-name>" }`
   - 若该仓库名已在 `folders` 中则跳过，避免重复
   - 保持 JSON 合法（注意逗号与引号）
4. clone 完成后提示用户重载窗口使新分工作区生效

### 情况 B：其他任意目录（默认）

不满足情况 A 的条件时，按标准 `git clone` 行为，clone 到**当前目录**下：

```bash
git clone <normalized-url>
```

### 情况 C：用户显式指定目标目录

若用户明确指定 clone 目标路径，以用户指定为准，跳过以上规则。

## 拉取流程

1. 归一化 URL（见“URL 主机替换规则”）
2. 判定目标位置（见“确定目标位置”）
3. 执行 `git clone`
   - 若目标目录已存在且是 git 仓库，向用户说明情况并选择：更新（`git pull`）或另换目录
4. 验证：进入克隆目录执行 `git status`、`git remote -v`，确认远端为归一化后的地址且仓库正常

## 注意事项

- 该 GitLab 是纯 HTTP 服务，URL 一律 `http://`，不要改成 `https://`
- 仓库地址形如 `http://<host>/<group>/<repo>.git`
- 不要替换用户明确给出的非 localhost 主机
- 修改 `Diff-Agent2.code-workspace` 时必须保证 JSON 语法正确
