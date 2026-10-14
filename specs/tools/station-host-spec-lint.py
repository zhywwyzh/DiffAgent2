#!/usr/bin/env python3
# Entity: station-host
# Invoked: 获得使用者检查许可后，通过 python3 手动调用
"""读取契约注册表并检查结构；不执行测试、不修改文件、不证明实现合规。"""

import argparse
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath
import re
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2], help="契约所属仓库根目录")
    args = parser.parse_args()
    registry = Registry(args.repo_root.resolve())
    try:
        registry.scan()
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        registry.error("specs", f"检查未完成（{type(exc).__name__}），不能给出通过结论")
    for message in registry.errors:
        print(message, file=sys.stderr)
    if registry.errors:
        print(f"结构检查发现 {len(registry.errors)} 项错误；不代表语义或实现结论。", file=sys.stderr)
        return 1
    print(f"读取 {len(registry.records)} 条记录，未发现结构错误。仍需人工语义审阅；不证明实现或验收通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
