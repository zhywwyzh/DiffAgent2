#!/usr/bin/env python3
# Entity: station-host
# Invoked: 获得使用者检查许可后，通过 python3 手动调用
"""结构与同步检查只读；基线模式仅写忽略区，不执行测试或证明实现合规。"""

import argparse
from dataclasses import dataclass, field
from datetime import date
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit


STATES = {"implemented", "proposed", "rejected", "archived"}
LIVE_STATES = {"implemented", "proposed"}
HISTORICAL_CUTOFF = date(2026, 10, 14)
SEGMENT = r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*"
ROOT_HEADINGS = ["范围", "不变量", "Inner contracts", "边界"]
LEAF_HEADINGS = [
    "范围与非目标", "术语与身份", "输入、输出与配置", "行为规则",
    "失败、取消与资源生命周期", "归属与依赖", "条款检查判据",
]
DECISION_HEADINGS = ["背景", "决策", "理由与放弃的选项", "影响", "关联契约与替代关系"]
RELATIONS = {"Supersedes", "Superseded-by"}


def relative_path(value, pattern=False):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("必须使用非空 POSIX 相对路径")
    parts = value.split("/")
    if value.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("路径不得绝对化、含空段或上级目录")
    if any(character in value for character in "[]{}\n\r\0"):
        raise ValueError("路径含不支持的字符")
    if not pattern and any(character in value for character in "*?"):
        raise ValueError("该路径不允许通配符")
    if pattern and any("**" in part and part != "**" for part in parts):
        raise ValueError("双星必须独占一个路径段")
    return value


def matches_path(pattern, path):
    parts = pattern.split("/")
    expression = ""
    for index, part in enumerate(parts):
        if part == "**":
            expression += ".*" if index == len(parts) - 1 else "(?:[^/]+/)*"
        else:
            expression += re.escape(part).replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
            if index != len(parts) - 1:
                expression += "/"
    return re.fullmatch(expression, path) is not None


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON 对象有重复键")
        result[key] = value
    return result


def json_block(text, label):
    blocks = re.findall(r"^```" + re.escape(label) + r"[ \t]*\n(.*?)^```[ \t]*$", text, re.M | re.S)
    if len(blocks) != 1:
        raise ValueError(f"必须有且仅有一个 {label} JSON 块")
    return json.loads(blocks[0], object_pairs_hook=unique_object)


def string_list(values, nonempty=False):
    return (
        isinstance(values, list) and (bool(values) or not nonempty)
        and all(isinstance(value, str) and bool(value.strip()) for value in values)
        and len(values) == len(set(values))
    )


def within(path, root):
    """使用路径包含关系，兼容未提供 Path.is_relative_to 的解释器。"""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def prose_lines(text):
    """保留行号，屏蔽 fenced code，避免把代码样例当作正文结构。"""
    result = []
    fence = None
    for line in text.splitlines():
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence is None and marker:
            fence = marker.group(1)
            result.append("")
        elif fence is not None:
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}\s*", line):
                fence = None
            result.append("")
        else:
            result.append(line)
    return result, fence is not None


@dataclass
class Record:
    path: str
    state: str
    kind: str
    text: str
    meta: dict = field(default_factory=dict)
    sections: dict = field(default_factory=dict)
    headings: list = field(default_factory=list)
    links: dict = field(default_factory=dict)


class Registry:
    def __init__(self, root):
        self.root = root
        self.records = {}
        self.errors = []

    def error(self, path, message, line=None):
        location = f"{path}:{line}" if line else path
        self.errors.append(f"{location}: {message}")

    def read(self, path):
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            self.error(path.relative_to(self.root).as_posix(), f"无法读取 UTF-8 文件（{type(exc).__name__}）")
            return None

    def scan(self):
        specs = self.root / "specs"
        if specs.is_symlink() or not specs.is_dir():
            self.error("specs", "必须是实际目录，不能是符号链接")
            return
        self.walk(specs)
        readme = specs / "README.md"
        if not readme.is_file():
            self.error("specs/README.md", "缺少编写规则入口")
        elif not readme.is_symlink():
            text = self.read(readme)
            if text is not None:
                lines, unclosed = prose_lines(text)
                if unclosed:
                    self.error("specs/README.md", "代码围栏未关闭")
                self.check_links("specs/README.md", lines)
        if not self.records:
            self.error("specs", "未发现契约或决策记录，不能给出结构通过结论")
        for record in self.records.values():
            self.check_record(record)
        self.check_contracts()
        self.check_relations()
        self.check_change_links()

    def walk(self, directory):
        for path in sorted(directory.iterdir()):
            relative = path.relative_to(self.root).as_posix()
            parts = path.relative_to(self.root / "specs").parts
            if path.is_symlink():
                self.error(relative, "不允许符号链接")
                continue
            if path.is_dir():
                allowed = (
                    len(parts) == 1 and parts[0] in STATES | {"tools"}
                    or len(parts) == 2 and parts[0] in STATES
                    and parts[1] in {"inner", "architecture", "process"}
                )
                if not allowed:
                    self.error(relative, "未知目录层级")
                    continue
                if not any(path.iterdir()):
                    self.error(relative, "不预建空目录")
                self.walk(path)
                continue
            if not path.is_file():
                self.error(relative, "不支持的文件类型")
                continue
            if parts == ("README.md",):
                continue
            if len(parts) == 2 and parts[0] == "tools":
                if not re.fullmatch(r"station-host-" + SEGMENT + r"\.py", parts[1]):
                    self.error(relative, "未知门禁文件；入口使用 station-host-<name>.py")
                else:
                    self.check_tool(path)
                continue
            kind = None
            if parts[0] in STATES:
                if len(parts) == 2 and re.fullmatch(SEGMENT + r"\.spec\.md", parts[-1]):
                    kind = "root"
                elif len(parts) == 3 and parts[1] == "inner" and "-" in parts[-1] and re.fullmatch(SEGMENT + r"\.spec\.md", parts[-1]):
                    kind = "leaf"
                elif len(parts) == 3 and parts[1] in {"architecture", "process"} and re.fullmatch(r"\d{4}-\d{2}-\d{2}-" + SEGMENT + r"\.md", parts[-1]):
                    kind = "decision"
            if kind is None:
                self.error(relative, "文件路径或命名不符合 F1")
                continue
            text = self.read(path)
            if text is not None:
                self.records[relative] = Record(relative, parts[0], kind, text)

    def check_tool(self, path):
        text = self.read(path)
        if text is None:
            return
        head = text.splitlines()[:8]
        relative = path.relative_to(self.root).as_posix()
        if "# Entity: station-host" not in head or not any(line.startswith("# Invoked: ") for line in head):
            self.error(relative, "门禁入口缺少 Entity 或 Invoked 头")

    def check_record(self, record):
        lines, unclosed = prose_lines(record.text)
        if unclosed:
            self.error(record.path, "代码围栏未关闭")
        raw = record.text.splitlines()
        if len(raw) < 4:
            self.error(record.path, "记录缺少公共头")
            return
        if not raw[0].startswith("# ") or not re.search(r"[\u4e00-\u9fff]", raw[0][2:]):
            self.error(record.path, "第 1 行必须是包含中文的一级标题", 1)
        if raw[1] != "":
            self.error(record.path, "第 2 行必须为空", 2)
        expected = "Status: " + record.state
        if record.state == "implemented":
            valid_status = raw[2] == expected
        else:
            valid_status = bool(re.fullmatch(re.escape(expected) + r" — .+", raw[2]) and re.search(r"[\u4e00-\u9fff]", raw[2]))
        if not valid_status:
            self.error(record.path, "第 3 行状态必须匹配生命周期目录，非生效状态须附中文理由", 3)
        for idx in range(2, len(raw)):
            if raw[idx] == "":
                break
            match = re.fullmatch(r"([A-Za-z][A-Za-z-]*): (.+)", raw[idx])
            if not match:
                self.error(record.path, "非法 header 行", idx + 1)
                continue
            name, value = match.groups()
            values = record.meta.setdefault(name, [])
            if values and name not in RELATIONS:
                self.error(record.path, f"重复 header 字段 {name}", idx + 1)
            if value in values:
                self.error(record.path, f"重复 header 值 {name}", idx + 1)
            values.append(value)
        fields = {"Status", "Date", "Record-Format"} | RELATIONS if record.kind == "decision" else {"Status", "Contract-ID"} | ({"Parent"} if record.kind == "leaf" else set())
        for name in record.meta.keys() - fields:
            self.error(record.path, f"未知 header 字段 {name}")
        if record.kind == "decision":
            required = [(3, "Date"), (4, "Record-Format")]
        else:
            required = [(3, "Contract-ID")]
            if record.kind == "leaf":
                required.append((4, "Parent"))
        for idx, name in required:
            if idx >= len(raw) or not raw[idx].startswith(name + ": "):
                self.error(record.path, f"第 {idx + 1} 行必须声明 {name}", idx + 1)
        starts = [(idx, line[3:]) for idx, line in enumerate(lines) if line.startswith("## ")]
        for pos, (idx, title) in enumerate(starts):
            end = starts[pos + 1][0] if pos + 1 < len(starts) else len(lines)
            if title in record.sections:
                self.error(record.path, f"重复章节 {title}", idx + 1)
            # 非空判断使用原文，含数据的代码块也是有效正文。
            body = "\n".join(raw[idx + 1:end]).strip()
            record.sections[title] = body
            record.headings.append(title)
            if not body:
                self.error(record.path, f"空章节 {title}", idx + 1)
        self.check_links(record.path, lines)
        if record.kind == "decision":
            self.check_decision(record)
        elif record.state in LIVE_STATES:
            expected_headings = ROOT_HEADINGS if record.kind == "root" else LEAF_HEADINGS
            if record.headings != expected_headings:
                self.error(record.path, "正文必须按顺序使用模板章节：" + "、".join(expected_headings))
        elif not any(line.strip() for line in lines[5:]):
            self.error(record.path, "历史记录不能只有 header，须保存理由及历史内容")

    @staticmethod
    def value(record, name):
        values = record.meta.get(name, [])
        return values[0] if values else ""

    def check_decision(self, record):
        declared = self.value(record, "Date")
        try:
            recorded_date = date.fromisoformat(declared)
        except ValueError:
            self.error(record.path, "Date 必须是有效 ISO 日期")
            return
        if declared != Path(record.path).name[:10]:
            self.error(record.path, "Date 与文件名日期不一致")
        format_name = self.value(record, "Record-Format")
        if format_name == "historical":
            if recorded_date >= HISTORICAL_CUTOFF:
                self.error(record.path, "新决策不得使用历史结构例外")
            if not record.text.split("\n\n", 2)[-1].strip():
                self.error(record.path, "历史决策正文为空")
        elif format_name == "structured":
            if record.headings != DECISION_HEADINGS:
                self.error(record.path, "决策正文必须按顺序使用模板章节：" + "、".join(DECISION_HEADINGS))
        else:
            self.error(record.path, "Record-Format 只能是 structured 或 historical")

    def check_contracts(self):
        ids = {}
        roots = []
        for record in self.records.values():
            if record.kind == "decision":
                continue
            contract_id = self.value(record, "Contract-ID")
            pattern = SEGMENT if record.kind == "root" else SEGMENT + "/" + SEGMENT
            if not re.fullmatch(pattern, contract_id):
                self.error(record.path, "Contract-ID 不符合根/叶身份格式")
            if record.state in LIVE_STATES:
                if contract_id in ids:
                    self.error(record.path, f"Contract-ID 与 {ids[contract_id]} 重复")
                ids[contract_id] = record.path
            if record.kind == "root":
                if Path(record.path).name != contract_id + ".spec.md":
                    self.error(record.path, "根文件名与 Contract-ID 的领域名不一致")
                if record.state == "implemented":
                    roots.append(record)
                    if len(record.text.splitlines()) > 400:
                        self.error(record.path, "生效根契约超过 400 行")
                continue
            parent_path = self.value(record, "Parent")
            parent = self.records.get(parent_path)
            if parent is None or parent.kind != "root":
                self.error(record.path, "Parent 必须精确指向本注册表根契约")
                continue
            if contract_id.split("/")[0] != self.value(parent, "Contract-ID"):
                self.error(record.path, "叶 ID 前缀与父根 ID 不一致")
            allowed = {"implemented"} if record.state == "implemented" else LIVE_STATES
            if record.state in LIVE_STATES and parent.state not in allowed:
                self.error(record.path, "父根生命周期不允许当前叶状态")
        if len(roots) > 10:
            self.error("specs/implemented", "根契约数量超过十份")
        for root in self.records.values():
            if root.kind != "root" or root.state not in LIVE_STATES:
                continue
            body = root.sections.get("Inner contracts", "")
            listed = []
            for row in body.splitlines():
                if not row.strip().startswith("|"):
                    continue
                cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
                if cells and (cells[0] == "契约路径" or re.fullmatch(r":?-+:?", cells[0])):
                    continue
                if len(cells) != 2:
                    self.error(root.path, "子契约表必须包含契约路径和职责两列")
                    continue
                match = re.search(r"specs/[^`\s)]+\.spec\.md", cells[0])
                if match is None or not cells[1]:
                    self.error(root.path, "子契约登记缺少精确路径或职责")
                    continue
                listed.append(match.group())
            expected = {record.path for record in self.records.values() if record.kind == "leaf" and record.state == root.state and self.value(record, "Parent") == root.path}
            for missing in sorted(expected - set(listed)):
                self.error(root.path, f"未登记叶契约 {missing}")
            for extra in sorted(set(listed) - expected):
                self.error(root.path, f"登记了不属于该根同状态的叶契约 {extra}")
            if len(listed) != len(set(listed)):
                self.error(root.path, "重复登记叶契约")

    def check_relations(self):
        graph = {}
        for record in self.records.values():
            if record.kind != "decision":
                continue
            graph[record.path] = record.meta.get("Supersedes", [])
            for field_name in RELATIONS:
                inverse = "Superseded-by" if field_name == "Supersedes" else "Supersedes"
                for target_path in record.meta.get(field_name, []):
                    target = self.records.get(target_path)
                    if target is None or target.kind != "decision":
                        self.error(record.path, f"{field_name} 必须指向实际决策记录：{target_path}")
                    elif target_path == record.path:
                        self.error(record.path, "决策不得替代自身")
                    elif record.path not in target.meta.get(inverse, []):
                        self.error(record.path, f"{target_path} 缺少反向 {inverse}")
        visited = set()
        active = set()

        def visit(path):
            if path in active:
                self.error(path, "决策替代关系存在环")
                return
            if path in visited:
                return
            active.add(path)
            for target in graph.get(path, []):
                visit(target)
            active.remove(path)
            visited.add(path)

        for path in graph:
            visit(path)

    def check_change_links(self):
        active = {self.value(record, "Contract-ID") for record in self.records.values()
                  if record.kind != "decision" and record.state in LIVE_STATES}
        for record in self.records.values():
            if record.kind != "leaf" or record.state not in LIVE_STATES:
                continue
            try:
                links = json_block(record.sections.get("归属与依赖", ""), "contract-links")
                if not isinstance(links, dict) or set(links) != {"implementation", "depends_on"}:
                    raise ValueError("关联块只允许 implementation 和 depends_on")
                if not string_list(links["implementation"], nonempty=True) or not string_list(links["depends_on"]):
                    raise ValueError("实现路径须为非空唯一数组，依赖须为唯一字符串数组")
                for pattern in links["implementation"]:
                    relative_path(pattern, pattern=True)
                parent = self.records.get(self.value(record, "Parent"))
                if parent and self.value(parent, "Contract-ID") not in links["depends_on"]:
                    raise ValueError("依赖必须显式声明父根的约束边界")
                for dependency in links["depends_on"]:
                    if dependency not in active or dependency == self.value(record, "Contract-ID"):
                        raise ValueError("依赖 ID 不存在、已失效或引用自身：" + dependency)
                record.links = links
            except (ValueError, TypeError) as exc:
                self.error(record.path, str(exc))

    def check_links(self, source, lines):
        inline = re.compile(r"!?\[[^\]\n]*\]\(\s*(?:<([^>\n]+)>|([^\s)]+))(?:\s+[\"'][^\n]*?[\"'])?\s*\)")
        reference = re.compile(r"^ {0,3}\[[^\]]+\]:\s*(?:<([^>]+)>|(\S+))")
        for idx, line in enumerate(lines, 1):
            matches = list(inline.finditer(line))
            definition = reference.match(line)
            if definition:
                matches.append(definition)
            for match in matches:
                target = match.group(1) or match.group(2)
                try:
                    parsed = urlsplit(target)
                    if parsed.scheme in {"http", "https", "mailto"} or parsed.netloc:
                        continue
                    if parsed.scheme:
                        self.error(source, "不支持的链接协议，文件引用须使用仓库内相对路径", idx)
                        continue
                    if not parsed.path:
                        continue
                    relative = unquote(parsed.path)
                    if PurePosixPath(relative).is_absolute():
                        self.error(source, "本地链接须使用仓库内相对路径", idx)
                        continue
                    unresolved = self.root / Path(source).parent / relative
                    resolved = unresolved.resolve()
                    if not within(resolved, self.root):
                        self.error(source, "本地链接越出仓库", idx)
                        continue
                    current = unresolved
                    while current != self.root and within(current, self.root):
                        if current.is_symlink():
                            self.error(source, "本地链接不得经由符号链接", idx)
                            break
                        current = current.parent
                    else:
                        if not resolved.is_file():
                            self.error(source, f"本地链接目标文件不存在：{relative}", idx)
                except (OSError, ValueError, RuntimeError):
                    self.error(source, "本地链接无法解析", idx)


class ChangeSync:
    def __init__(self, registry):
        self.registry = registry
        self.root = registry.root

    def git(self, *arguments):
        options = ["--literal-pathspecs"] if arguments[0] == "ls-files" else []
        return subprocess.run(["git", "-C", str(self.root), *options, *arguments],
                              check=True, capture_output=True).stdout

    def local_file(self, name):
        relative_path(name)
        path = self.root / name
        if not within(path.resolve(), self.root):
            raise ValueError("路径越出当前仓库")
        current = path
        while current != self.root:
            if current.is_symlink():
                raise ValueError("文件路径不得经由符号链接")
            current = current.parent
        return path

    def ignored_file(self, name):
        path = self.local_file(name)
        if not name.startswith(".artifacts/spec-sync/") or not name.endswith(".json"):
            raise ValueError("基线只允许使用 .artifacts/spec-sync/ 下的 JSON，不读取其它主机本地文件")
        self.git("check-ignore", "-q", "--", name)
        return path

    @staticmethod
    def in_scope(name, scopes):
        return any(name == scope or name.startswith(scope + "/") for scope in scopes)

    def files(self, scopes):
        if not string_list(scopes, nonempty=True):
            raise ValueError("任务范围必须是非空唯一相对路径数组")
        for scope in scopes:
            relative_path(scope)
        output = self.git("ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *scopes)
        result = {}
        for name in sorted({part.decode("utf-8") for part in output.split(b"\0") if part}):
            if not self.in_scope(name, scopes):
                raise ValueError("Git 返回了任务范围之外的路径")
            path = self.local_file(name)
            if path.exists() and not path.is_file():
                raise ValueError("任务范围含目录 gitlink 或非普通文件：" + name)
            if path.is_file():
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                result[name] = digest.hexdigest()
            else:
                result[name] = None
        return result

    def contracts(self):
        records = [record for record in self.registry.records.values()
                   if record.kind != "decision" and record.state in LIVE_STATES]
        identities = {record.path: self.registry.value(record, "Contract-ID") for record in records}
        return {
            self.registry.value(record, "Contract-ID"): {
                "path": record.path,
                "parent": identities.get(self.registry.value(record, "Parent")),
                "implementation": record.links.get("implementation", []),
                "depends_on": record.links.get("depends_on", []),
            } for record in records
        }

    def capture(self, name, scopes):
        destination = self.ignored_file(name)
        snapshot = {
            "schema": 1,
            "repo_id": hashlib.sha256(str(self.root).encode()).hexdigest(),
            "head": self.git("rev-parse", "HEAD").decode().strip(),
            "scopes": scopes,
            "files": self.files(scopes),
            "contracts": self.contracts(),
        }
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"baseline": name, "baseline_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                          "files": len(snapshot["files"])}, ensure_ascii=False))

    def load(self, plan_name):
        plan = json_block(self.local_file(plan_name).read_text(encoding="utf-8"), "contract-sync")
        if not isinstance(plan, dict) or set(plan) != {"baseline", "baseline_sha256", "reviews"}:
            raise ValueError("同步块必须且仅声明 baseline、baseline_sha256 和 reviews")
        if not isinstance(plan["baseline_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", plan["baseline_sha256"]):
            raise ValueError("基线摘要须为 SHA-256")
        raw = self.ignored_file(plan["baseline"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != plan["baseline_sha256"]:
            raise ValueError("基线摘要不符，不能使用被覆盖的起点")
        baseline = json.loads(raw, object_pairs_hook=unique_object)
        if not isinstance(baseline, dict) or set(baseline) != {"schema", "repo_id", "head", "scopes", "files", "contracts"}:
            raise ValueError("基线字段不完整")
        if type(baseline["schema"]) is not int or baseline["schema"] != 1:
            raise ValueError("不支持的基线 schema")
        if baseline["repo_id"] != hashlib.sha256(str(self.root).encode()).hexdigest():
            raise ValueError("基线不属于当前仓库位置")
        if not isinstance(baseline["head"], str) or not re.fullmatch(r"[0-9a-f]{40,64}", baseline["head"]):
            raise ValueError("基线缺少有效提交身份")
        if not isinstance(baseline["files"], dict) or not isinstance(baseline["contracts"], dict):
            raise ValueError("基线文件及契约图必须为对象")
        current = self.files(baseline["scopes"])
        for name, digest in baseline["files"].items():
            relative_path(name)
            if not self.in_scope(name, baseline["scopes"]):
                raise ValueError("基线文件越出原任务范围")
            if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
                raise ValueError("基线文件指纹无效")
        changed = {name for name in set(current) | set(baseline["files"])
                   if current.get(name) != baseline["files"].get(name)}
        graph = {}
        for version in (baseline["contracts"], self.contracts()):
            for identity, info in version.items():
                if not isinstance(identity, str) or not re.fullmatch(SEGMENT + r"(?:/" + SEGMENT + ")?", identity):
                    raise ValueError("基线关联图有非法 Contract-ID")
                if not isinstance(info, dict) or set(info) != {"path", "parent", "implementation", "depends_on"}:
                    raise ValueError("基线契约关联字段不完整")
                relative_path(info["path"])
                if not string_list(info["implementation"]) or not string_list(info["depends_on"]):
                    raise ValueError("基线关联数组无效")
                for pattern in info["implementation"]:
                    relative_path(pattern, pattern=True)
                if info["parent"] is not None and not isinstance(info["parent"], str):
                    raise ValueError("基线父根 ID 无效")
                entry = graph.setdefault(identity, {"paths": set(), "parents": set(), "implementation": set(), "depends_on": set()})
                entry["paths"].add(info["path"])
                if info["parent"]:
                    entry["parents"].add(info["parent"])
                entry["implementation"].update(info["implementation"])
                entry["depends_on"].update(info["depends_on"])
        for info in graph.values():
            if not (info["parents"] | info["depends_on"]) <= graph.keys():
                raise ValueError("基线关联图有无法解析的依赖或父根")
        candidates = {}
        unmapped = []
        for name in sorted(changed):
            owners = {identity for identity, info in graph.items()
                      if name in info["paths"] or any(matches_path(pattern, name) for pattern in info["implementation"])}
            if not owners:
                unmapped.append(name)
            for identity in owners:
                candidates.setdefault(identity, set()).add("文件变更：" + name)
        pending = list(candidates)
        while pending:
            affected = pending.pop()
            for identity, info in graph.items():
                if affected in info["depends_on"]:
                    fresh = identity not in candidates
                    candidates.setdefault(identity, set()).add("反向依赖：" + affected)
                    if fresh:
                        pending.append(identity)
        # 父子登记只加入父根，不从父根向下展开同级契约。
        for identity in list(candidates):
            for parent in graph[identity]["parents"]:
                candidates.setdefault(parent, set()).add("父根登记：" + identity)
        return plan, baseline, graph, changed, candidates, unmapped

    def check(self, plan_name, list_only=False):
        plan, baseline, graph, changed, candidates, unmapped = self.load(plan_name)
        if list_only:
            print(json.dumps({"changed_files": sorted(changed),
                              "candidates": {key: sorted(value) for key, value in sorted(candidates.items())},
                              "unmapped": unmapped}, ensure_ascii=False, indent=2))
            print("以上是候选影响报告，不表示同步完成。")
            return
        for name in unmapped:
            self.registry.error(plan_name, "改动没有契约绑定，必须补充归属：" + name)
        if not isinstance(plan["reviews"], list):
            raise ValueError("reviews 必须为数组")
        reviewed = set()
        for review in plan["reviews"]:
            if not isinstance(review, dict) or set(review) != {"id", "clauses", "status", "reason", "evidence"}:
                self.registry.error(plan_name, "处置记录字段不完整或有未知字段")
                continue
            identity = review["id"]
            if not isinstance(identity, str) or identity not in graph or identity in reviewed:
                self.registry.error(plan_name, "处置 ID 未知或重复")
                continue
            reviewed.add(identity)
            if not string_list(review["clauses"], nonempty=True):
                self.registry.error(plan_name, "缺少具体条款定位：" + identity)
            else:
                records = [record for record in self.registry.records.values()
                           if record.kind != "decision" and record.state in LIVE_STATES
                           and self.registry.value(record, "Contract-ID") == identity]
                for clause in review["clauses"]:
                    if not records:
                        valid = clause in {"整体删除", "整体归档"}
                    else:
                        lines, _ = prose_lines(records[0].text)
                        headings = [line.lstrip("# ") for line in lines if re.match(r"^#{2,6} ", line)]
                        number = re.fullmatch(r"§(\d+(?:\.\d+)*)", clause)
                        if number:
                            valid = any(re.match(re.escape(number.group(1)) + r"(?:\.\s|\s)", heading) for heading in headings)
                        elif "/" in clause:
                            pieces = clause.split("/")
                            index = 0
                            for heading in headings:
                                if index < len(pieces) and heading == pieces[index]:
                                    index += 1
                            valid = index == len(pieces)
                        else:
                            valid = clause in headings or bool(re.fullmatch(r"[A-Z]+\d+", clause) and re.search(r"\b" + re.escape(clause) + r"\b", "\n".join(lines)))
                    if not valid:
                        self.registry.error(plan_name, "条款定位不存在：" + identity + " / " + clause)
            reason = review["reason"]
            if not isinstance(reason, str) or len(reason.strip()) < 8 or not re.search(r"[\u4e00-\u9fff]", reason):
                self.registry.error(plan_name, "缺少具体中文处置理由：" + identity)
            status = review["status"]
            if status not in {"updated", "unchanged"}:
                self.registry.error(plan_name, "处置仍待同步或状态非法：" + identity)
            contract_changed = bool(graph[identity]["paths"] & changed)
            if status == "updated" and not contract_changed:
                self.registry.error(plan_name, "声明 updated 但契约文件未变：" + identity)
            if status == "unchanged" and contract_changed:
                self.registry.error(plan_name, "契约文件已变，不能声明 unchanged：" + identity)
            if not string_list(review["evidence"], nonempty=True):
                self.registry.error(plan_name, "缺少文件证据：" + identity)
                continue
            for name in review["evidence"]:
                try:
                    file = self.local_file(name)
                    if not file.is_file() and baseline["files"].get(name) is None:
                        raise ValueError("证据文件不存在且没有删除前的基线指纹")
                except ValueError as exc:
                    self.registry.error(plan_name, f"{identity}：{exc}")
        for identity in sorted(candidates.keys() - reviewed):
            self.registry.error(plan_name, "漏处置配套契约：" + identity)
        if not self.registry.errors:
            print(f"本轮 {len(changed)} 个变更文件、{len(candidates)} 个候选契约已逐项处置；仅证明覆盖与记录完整，不证明业务或外部仓库通过。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2], help="契约所属仓库根目录")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--capture-baseline", metavar="本地文件", help="写入尚不存在的 Git 忽略区基线")
    modes.add_argument("--list-impacts", metavar="方案", help="只报告任务候选契约，不作同步通过结论")
    modes.add_argument("--sync-plan", metavar="方案", help="检查任务差异的配套契约处置记录")
    parser.add_argument("--scope", action="append", help="基线任务范围，可重复，仅用于基线捕获")
    args = parser.parse_args()
    if bool(args.capture_baseline) != bool(args.scope):
        parser.error("基线捕获必须同时提供 --capture-baseline 和至少一个 --scope；其它模式不得提供 --scope")
    registry = Registry(args.repo_root.resolve())
    try:
        registry.scan()
        if not registry.errors:
            sync = ChangeSync(registry)
            if args.capture_baseline:
                sync.capture(args.capture_baseline, args.scope)
            elif args.list_impacts:
                sync.check(args.list_impacts, list_only=True)
            elif args.sync_plan:
                sync.check(args.sync_plan)
    except (OSError, UnicodeError, TypeError, ValueError, RecursionError, subprocess.CalledProcessError) as exc:
        if isinstance(exc, (ValueError, TypeError)):
            registry.error("specs", "检查未完成：" + str(exc))
        else:
            registry.error("specs", f"检查未完成（{type(exc).__name__}），不能给出通过结论")
    for message in registry.errors:
        print(message, file=sys.stderr)
    if registry.errors:
        print(f"文档／同步检查发现 {len(registry.errors)} 项错误；不代表语义或实现结论。", file=sys.stderr)
        return 1
    if args.capture_baseline:
        return 0
    print(f"读取 {len(registry.records)} 条记录，未发现结构错误。仍需人工语义审阅；不证明实现或验收通过。")
    if not args.sync_plan and not args.list_impacts:
        print("默认模式未执行任务差异的配套契约同步核对，不能据此声明同步完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
