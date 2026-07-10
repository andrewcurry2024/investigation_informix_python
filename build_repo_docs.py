#!/usr/bin/env python3
"""
build_repo_docs.py

Generate useful GitHub/MkDocs documentation for a repository of standalone Python scripts.

What it creates:
  - README.md (or another chosen file) with a proper repo overview and script index
  - docs/<script>.md for each Python script
  - optional mkdocs.yml

It is designed for operational/tooling repos like an Informix investigation toolkit where each
script has argparse options, file inputs, CSV/PDF/PNG outputs, and practical usage examples.

Example:
  python build_repo_docs.py --repo-root . --docs-dir docs --readme README.md --mkdocs --force
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


STD_LIB_GUESS = {
    "abc", "argparse", "ast", "asyncio", "base64", "collections", "concurrent", "contextlib",
    "copy", "csv", "dataclasses", "datetime", "decimal", "difflib", "enum", "fnmatch", "functools",
    "glob", "gzip", "hashlib", "html", "io", "itertools", "json", "logging", "math", "multiprocessing",
    "operator", "os", "pathlib", "pickle", "platform", "pprint", "queue", "random", "re", "shlex",
    "shutil", "signal", "socket", "sqlite3", "statistics", "string", "subprocess", "sys", "tempfile",
    "textwrap", "threading", "time", "traceback", "typing", "unittest", "urllib", "uuid", "warnings",
    "xml", "zipfile",
}

DEFAULT_EXCLUDES = {
    ".git", ".hg", ".svn", ".mypy_cache", ".pytest_cache", ".tox", ".venv", "venv",
    "env", "__pycache__", "site-packages", "dist", "build", "node_modules", ".idea", ".vscode",
}

FILE_EXT_HINTS = {
    ".csv": "CSV file",
    ".tsv": "TSV file",
    ".txt": "text file",
    ".log": "log file",
    ".out": "output/text dump",
    ".json": "JSON file",
    ".xlsx": "Excel workbook",
    ".xls": "Excel workbook",
    ".png": "PNG image",
    ".jpg": "JPEG image",
    ".jpeg": "JPEG image",
    ".pdf": "PDF report",
    ".md": "Markdown file",
    ".html": "HTML file",
}

ARG_VALUE_OPTIONS = {"default", "help", "required", "choices", "action", "nargs", "type", "metavar", "dest"}


@dataclass
class CliOption:
    flags: List[str] = field(default_factory=list)
    help: str = ""
    required: Optional[bool] = None
    default: Optional[str] = None
    choices: Optional[str] = None
    action: Optional[str] = None
    nargs: Optional[str] = None
    type_name: Optional[str] = None
    metavar: Optional[str] = None
    dest: Optional[str] = None

    @property
    def display_flags(self) -> str:
        return ", ".join(self.flags) if self.flags else self.dest or "argument"

    @property
    def is_positional(self) -> bool:
        return bool(self.flags) and not self.flags[0].startswith("-")


@dataclass
class FunctionInfo:
    name: str
    signature: str
    doc: str
    lineno: int
    is_private: bool = False


@dataclass
class ClassInfo:
    name: str
    doc: str
    lineno: int
    methods: List[FunctionInfo] = field(default_factory=list)


@dataclass
class FileAccess:
    kind: str
    method: str
    value: str
    lineno: int


@dataclass
class ScriptDoc:
    path: Path
    rel_path: Path
    module_doc: str = ""
    parser_description: str = ""
    parser_epilog: str = ""
    imports: Set[str] = field(default_factory=set)
    cli_options: List[CliOption] = field(default_factory=list)
    functions: List[FunctionInfo] = field(default_factory=list)
    classes: List[ClassInfo] = field(default_factory=list)
    file_accesses: List[FileAccess] = field(default_factory=list)
    has_main_guard: bool = False
    syntax_error: Optional[str] = None

    @property
    def stem(self) -> str:
        return self.path.stem

    @property
    def title(self) -> str:
        return self.path.name

    @property
    def summary(self) -> str:
        desc = first_sentence(self.module_doc) or first_sentence(self.parser_description)
        if desc:
            return desc
        return infer_summary_from_name(self.path.stem)

    @property
    def external_dependencies(self) -> List[str]:
        return sorted(i for i in self.imports if i and i.split(".")[0] not in STD_LIB_GUESS)


def first_sentence(text: str) -> str:
    text = clean_text(text)
    if not text:
        return ""
    # Keep first non-empty paragraph, then first sentence-ish line.
    para = next((p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()), text)
    line = " ".join(para.split())
    m = re.match(r"(.{20,220}?[.!?])\s", line + " ")
    return m.group(1).strip() if m else line[:220].strip()


def clean_text(text: Optional[str]) -> str:
    if not text:
        return ""
    return "\n".join(line.rstrip() for line in str(text).strip().splitlines()).strip()


def md_escape(text: Any) -> str:
    s = "" if text is None else str(text)
    return s.replace("|", "\\|").replace("\n", "<br>")


def ast_literal(node: ast.AST) -> Optional[Any]:
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def ast_to_short(node: ast.AST) -> str:
    val = ast_literal(node)
    if val is not None:
        if isinstance(val, str):
            return val
        return repr(val)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = ast_to_short(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return ast_to_short(node.func) + "(...)"
    try:
        return ast.unparse(node)
    except Exception:
        return "<expr>"


def call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        left = ast_to_short(node.func.value)
        return f"{left}.{node.func.attr}" if left else node.func.attr
    return ast_to_short(node.func)


def function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    parts: List[str] = []
    total_args = list(node.args.posonlyargs) + list(node.args.args)
    defaults = [None] * (len(total_args) - len(node.args.defaults)) + list(node.args.defaults)
    for arg, default in zip(total_args, defaults):
        item = arg.arg
        if default is not None:
            item += "=" + ast_to_short(default)
        parts.append(item)
    if node.args.vararg:
        parts.append("*" + node.args.vararg.arg)
    elif node.args.kwonlyargs:
        parts.append("*")
    for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
        item = arg.arg
        if default is not None:
            item += "=" + ast_to_short(default)
        parts.append(item)
    if node.args.kwarg:
        parts.append("**" + node.args.kwarg.arg)
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    return f"{prefix}{node.name}({', '.join(parts)})"


def infer_summary_from_name(stem: str) -> str:
    words = stem.replace("_", " ").replace("-", " ").strip()
    lower = words.lower()
    if "rss" in lower and "plot" in lower:
        return "Analyse and plot Informix RSS replication metrics."
    if "rss" in lower:
        return "Analyse Informix RSS replication data."
    if "osmon" in lower:
        return "Summarise OSMON/storage performance data."
    if "iostat" in lower:
        return "Collect or summarise Linux iostat disk performance data."
    if "thread" in lower:
        return "Analyse Informix thread or stack output."
    if "ppf" in lower or "compare" in lower or "comp" in lower:
        return "Compare diagnostic/input files and report differences."
    if "latency" in lower:
        return "Analyse latency metrics and produce a summary."
    return f"Utility script for {words}."


class RepoDocAnalyzer(ast.NodeVisitor):
    def __init__(self, script: ScriptDoc, include_private: bool = False) -> None:
        self.script = script
        self.include_private = include_private
        self.class_stack: List[ClassInfo] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.script.imports.add(alias.name.split(".")[0])
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            self.script.imports.add(node.module.split(".")[0])
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node.name.startswith("_") and not self.include_private:
            return
        cls = ClassInfo(
            name=node.name,
            doc=clean_text(ast.get_docstring(node) or ""),
            lineno=getattr(node, "lineno", 0),
        )
        self.script.classes.append(cls)
        self.class_stack.append(cls)
        for child in node.body:
            self.visit(child)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        is_private = node.name.startswith("_") and node.name not in {"__init__", "__main__"}
        if is_private and not self.include_private:
            return
        info = FunctionInfo(
            name=node.name,
            signature=function_signature(node),
            doc=clean_text(ast.get_docstring(node) or ""),
            lineno=getattr(node, "lineno", 0),
            is_private=is_private,
        )
        if self.class_stack:
            self.class_stack[-1].methods.append(info)
        else:
            self.script.functions.append(info)
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        # Detect if __name__ == "__main__"
        try:
            test = ast.unparse(node.test)
        except Exception:
            test = ""
        if "__name__" in test and "__main__" in test:
            self.script.has_main_guard = True
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        c_name = call_name(node)
        attr = c_name.split(".")[-1]

        if attr == "ArgumentParser":
            for kw in node.keywords:
                if kw.arg == "description":
                    self.script.parser_description = clean_text(ast_to_short(kw.value))
                elif kw.arg == "epilog":
                    self.script.parser_epilog = clean_text(ast_to_short(kw.value))

        if attr == "add_argument":
            self.script.cli_options.append(parse_add_argument(node))

        fa = detect_file_access(node, c_name)
        if fa:
            self.script.file_accesses.append(fa)

        self.generic_visit(node)


def parse_add_argument(node: ast.Call) -> CliOption:
    opt = CliOption()
    for arg in node.args:
        val = ast_literal(arg)
        if isinstance(val, str):
            opt.flags.append(val)
    for kw in node.keywords:
        if kw.arg not in ARG_VALUE_OPTIONS:
            continue
        value = ast_to_short(kw.value)
        if kw.arg == "help":
            opt.help = value
        elif kw.arg == "required":
            lit = ast_literal(kw.value)
            opt.required = bool(lit) if lit is not None else None
        elif kw.arg == "default":
            opt.default = value
        elif kw.arg == "choices":
            opt.choices = value
        elif kw.arg == "action":
            opt.action = value
        elif kw.arg == "nargs":
            opt.nargs = value
        elif kw.arg == "type":
            opt.type_name = value
        elif kw.arg == "metavar":
            opt.metavar = value
        elif kw.arg == "dest":
            opt.dest = value
    return opt


def detect_file_access(node: ast.Call, c_name: str) -> Optional[FileAccess]:
    attr = c_name.split(".")[-1]
    line = getattr(node, "lineno", 0)

    read_methods = {
        "read_csv", "read_excel", "read_json", "read_table", "read_fwf", "loadtxt", "genfromtxt",
        "read_text", "read_bytes",
    }
    write_methods = {
        "to_csv", "to_excel", "to_json", "to_markdown", "savefig", "write_text", "write_bytes",
        "PdfPages", "save", "dump", "dumpfig",
    }

    if attr == "open" or c_name == "open":
        value = ast_to_short(node.args[0]) if node.args else "file"
        mode = "r"
        if len(node.args) >= 2:
            mode = ast_to_short(node.args[1])
        for kw in node.keywords:
            if kw.arg == "mode":
                mode = ast_to_short(kw.value)
        kind = "output" if any(m in mode for m in ["w", "a", "x", "+"]) else "input"
        return FileAccess(kind=kind, method="open", value=value, lineno=line)

    if attr in read_methods:
        value = ast_to_short(node.args[0]) if node.args else "input"
        return FileAccess(kind="input", method=attr, value=value, lineno=line)

    if attr in write_methods:
        value = ast_to_short(node.args[0]) if node.args else "output"
        return FileAccess(kind="output", method=attr, value=value, lineno=line)

    return None


def iter_python_files(root: Path, excludes: Set[str]) -> Iterable[Path]:
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in excludes]
        for filename in filenames:
            if filename.endswith(".py"):
                yield Path(current_root) / filename


def analyse_script(path: Path, root: Path, include_private: bool = False) -> ScriptDoc:
    rel = path.relative_to(root)
    script = ScriptDoc(path=path, rel_path=rel)
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        source = path.read_text(encoding="latin-1")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        script.syntax_error = f"{exc.msg} at line {exc.lineno}"
        return script
    script.module_doc = clean_text(ast.get_docstring(tree) or "")
    RepoDocAnalyzer(script, include_private=include_private).visit(tree)
    return script


def option_example_value(opt: CliOption) -> str:
    flags_text = opt.display_flags.lower()
    help_text = (opt.help or "").lower()
    joined = flags_text + " " + help_text
    if opt.action in {"store_true", "store_false", "count"}:
        return ""
    if "csv" in joined:
        return "data.csv"
    if "excel" in joined or "xlsx" in joined:
        return "data.xlsx"
    if "pdf" in joined:
        return "report.pdf"
    if "png" in joined or "plot" in joined or "graph" in joined:
        return "plot.png"
    if "dir" in joined or "folder" in joined or "directory" in joined:
        return "./data"
    if "start" in joined and ("date" in joined or "time" in joined):
        return "2026-07-01"
    if "end" in joined and ("date" in joined or "time" in joined):
        return "2026-07-02"
    if "top" in joined or "limit" in joined or "count" in joined:
        return "10"
    if "interval" in joined or flags_text in {"-i", "--interval"}:
        return "2"
    if opt.choices:
        choices = re.findall(r"['\"]([^'\"]+)['\"]", opt.choices)
        if choices:
            return choices[0]
    if opt.default and opt.default not in {"None", "False", "True"}:
        return str(opt.default)
    return "VALUE"


def build_example_command(script: ScriptDoc) -> str:
    args: List[str] = []
    # Prefer required options and positionals. Add output if obvious.
    selected: List[CliOption] = []
    for opt in script.cli_options:
        if opt.is_positional or opt.required:
            selected.append(opt)
    if not selected:
        for opt in script.cli_options:
            text = opt.display_flags.lower() + " " + opt.help.lower()
            if any(k in text for k in ["input", "file", "csv", "directory", "folder"]):
                selected.append(opt)
            if len(selected) >= 2:
                break
    for opt in selected[:5]:
        flag = opt.flags[-1] if opt.flags else opt.dest or "ARG"
        value = option_example_value(opt)
        if opt.is_positional:
            args.append(value)
        elif value:
            args.append(f"{flag} {value}")
        else:
            args.append(flag)
    if args:
        return "python " + str(script.rel_path).replace(os.sep, "/") + " \\\n    " + " \\\n    ".join(args)
    return "python " + str(script.rel_path).replace(os.sep, "/")


def file_access_table(accesses: List[FileAccess], kind: str) -> List[str]:
    rows = []
    seen = set()
    for fa in accesses:
        if fa.kind != kind:
            continue
        key = (fa.method, fa.value)
        if key in seen:
            continue
        seen.add(key)
        hint = infer_file_hint(fa.value, fa.method)
        rows.append(f"| `{md_escape(fa.value)}` | {md_escape(fa.method)} | {hint} | line {fa.lineno} |")
    return rows


def infer_file_hint(value: str, method: str) -> str:
    lower = value.lower()
    for ext, desc in FILE_EXT_HINTS.items():
        if ext in lower:
            return desc
    if method in {"read_csv", "to_csv"}:
        return "CSV file"
    if method in {"read_excel", "to_excel"}:
        return "Excel workbook"
    if method == "savefig":
        return "image/plot output"
    if method == "PdfPages" or "pdf" in lower:
        return "PDF report"
    return "file/path expression"


def write_script_doc(script: ScriptDoc, docs_dir: Path, root: Path) -> Path:
    out = docs_dir / f"{script.stem}.md"
    lines: List[str] = []
    rel_code = str(script.rel_path).replace(os.sep, "/")

    lines.append(f"# {script.title}")
    lines.append("")
    lines.append("## Purpose")
    lines.append("")
    lines.append(script.summary)
    lines.append("")
    if script.module_doc and script.module_doc != script.summary:
        lines.append("### Module notes")
        lines.append("")
        lines.append(script.module_doc)
        lines.append("")
    if script.parser_description and script.parser_description not in script.module_doc:
        lines.append("### CLI description")
        lines.append("")
        lines.append(script.parser_description)
        lines.append("")

    lines.append("## Location")
    lines.append("")
    lines.append(f"`{rel_code}`")
    lines.append("")

    lines.append("## Usage")
    lines.append("")
    lines.append("```bash")
    lines.append(build_example_command(script))
    lines.append("```")
    lines.append("")

    if script.cli_options:
        lines.append("## Command line options")
        lines.append("")
        lines.append("| Option | Required | Default | Choices | Description |")
        lines.append("|---|---:|---|---|---|")
        for opt in script.cli_options:
            required = "Yes" if opt.required or opt.is_positional else "No"
            default = opt.default or ""
            choices = opt.choices or ""
            desc = opt.help or ""
            extra = []
            if opt.action:
                extra.append(f"action: `{opt.action}`")
            if opt.nargs:
                extra.append(f"nargs: `{opt.nargs}`")
            if opt.type_name:
                extra.append(f"type: `{opt.type_name}`")
            if extra:
                desc = (desc + " " if desc else "") + "(" + ", ".join(extra) + ")"
            lines.append(f"| `{md_escape(opt.display_flags)}` | {required} | `{md_escape(default)}` | `{md_escape(choices)}` | {md_escape(desc)} |")
        lines.append("")
    else:
        lines.append("## Command line options")
        lines.append("")
        lines.append("No argparse options detected.")
        lines.append("")

    input_rows = file_access_table(script.file_accesses, "input")
    output_rows = file_access_table(script.file_accesses, "output")

    lines.append("## Detected inputs")
    lines.append("")
    if input_rows:
        lines.append("| Path/expression | Method | Type | Code location |")
        lines.append("|---|---|---|---|")
        lines.extend(input_rows)
    else:
        lines.append("No file inputs detected statically.")
    lines.append("")

    lines.append("## Detected outputs")
    lines.append("")
    if output_rows:
        lines.append("| Path/expression | Method | Type | Code location |")
        lines.append("|---|---|---|---|")
        lines.extend(output_rows)
    else:
        lines.append("No file outputs detected statically.")
    lines.append("")

    lines.append("## Dependencies")
    lines.append("")
    deps = script.external_dependencies
    if deps:
        for dep in deps:
            lines.append(f"- `{dep}`")
    else:
        lines.append("No third-party imports detected. The script appears to use the Python standard library only.")
    lines.append("")

    if script.functions:
        lines.append("## Functions")
        lines.append("")
        for f in script.functions:
            lines.append(f"### `{f.signature}`")
            lines.append("")
            lines.append(f.doc or "No function docstring detected.")
            lines.append("")

    if script.classes:
        lines.append("## Classes")
        lines.append("")
        for c in script.classes:
            lines.append(f"### `{c.name}`")
            lines.append("")
            lines.append(c.doc or "No class docstring detected.")
            lines.append("")
            if c.methods:
                lines.append("| Method | Description |")
                lines.append("|---|---|")
                for m in c.methods:
                    lines.append(f"| `{md_escape(m.signature)}` | {md_escape(first_sentence(m.doc) or 'No method docstring detected.')} |")
                lines.append("")

    lines.append("## Notes")
    lines.append("")
    if script.syntax_error:
        lines.append(f"- This file could not be fully parsed: `{script.syntax_error}`")
    lines.append("- This page was generated by `build_repo_docs.py` using static AST analysis.")
    lines.append("- Review examples and detected input/output paths before publishing if the script builds paths dynamically.")
    lines.append("")

    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def read_requirements(root: Path) -> List[str]:
    req = root / "requirements.txt"
    if not req.exists():
        return []
    values = []
    for line in req.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        values.append(line)
    return values


def write_readme(scripts: List[ScriptDoc], root: Path, docs_dir: Path, readme_path: Path, project_name: str) -> None:
    all_deps = sorted({d for s in scripts for d in s.external_dependencies})
    reqs = read_requirements(root)
    rel_docs = docs_dir.relative_to(root) if docs_dir.is_relative_to(root) else docs_dir

    lines: List[str] = []
    lines.append(f"# {project_name}")
    lines.append("")
    lines.append("Python tooling repository containing standalone investigation and analysis scripts.")
    lines.append("")
    lines.append("The generated documentation below is intended to make each script easier to run, review, and maintain. It is especially useful for operational scripts where the important behaviour is often captured in command line options, inputs, outputs, and generated reports rather than in package-level API docs.")
    lines.append("")

    lines.append("## What is in this repository?")
    lines.append("")
    lines.append(f"- **Python scripts detected:** {len(scripts)}")
    lines.append(f"- **Per-script documentation:** `{str(rel_docs).replace(os.sep, '/')}/`")
    if reqs:
        lines.append("- **Dependencies file:** `requirements.txt`")
    lines.append("")

    lines.append("## Getting started")
    lines.append("")
    lines.append("```bash")
    lines.append("python -m venv .venv")
    lines.append("source .venv/bin/activate")
    if reqs:
        lines.append("pip install -r requirements.txt")
    elif all_deps:
        lines.append("pip install " + " ".join(all_deps))
    else:
        lines.append("# No third-party dependencies detected")
    lines.append("```")
    lines.append("")

    lines.append("## Script index")
    lines.append("")
    lines.append("| Script | Purpose | CLI options | Dependencies | Documentation |")
    lines.append("|---|---|---:|---|---|")
    for s in sorted(scripts, key=lambda x: str(x.rel_path)):
        doc_link = f"{str(rel_docs).replace(os.sep, '/')}/{s.stem}.md"
        dep_txt = ", ".join(f"`{d}`" for d in s.external_dependencies[:6])
        if len(s.external_dependencies) > 6:
            dep_txt += ", ..."
        if not dep_txt:
            dep_txt = "stdlib only"
        lines.append(
            f"| `{md_escape(str(s.rel_path).replace(os.sep, '/'))}` | {md_escape(s.summary)} | {len(s.cli_options)} | {dep_txt} | [docs]({doc_link}) |"
        )
    lines.append("")

    lines.append("## Documentation workflow")
    lines.append("")
    lines.append("Regenerate the README and per-script Markdown files after changing script arguments or behaviour:")
    lines.append("")
    lines.append("```bash")
    lines.append("python build_repo_docs.py --repo-root . --docs-dir docs --readme README.md --mkdocs --force")
    lines.append("```")
    lines.append("")

    lines.append("If using MkDocs locally:")
    lines.append("")
    lines.append("```bash")
    lines.append("pip install mkdocs mkdocs-material")
    lines.append("mkdocs serve")
    lines.append("```")
    lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append("- Documentation is generated using static analysis, so dynamic file paths may need a quick manual check.")
    lines.append("- The per-script pages are usually the most useful part of the generated output because they include options, usage, detected inputs, detected outputs, functions, and dependencies.")
    lines.append("- Keep meaningful module docstrings and argparse help text in the scripts; that gives the generator better source material.")
    lines.append("")

    readme_path.write_text("\n".join(lines), encoding="utf-8")


def write_mkdocs_yml(root: Path, docs_dir: Path, scripts: List[ScriptDoc], project_name: str, force: bool) -> Optional[Path]:
    out = root / "mkdocs.yml"
    if out.exists() and not force:
        return None
    rel_docs = docs_dir.relative_to(root) if docs_dir.is_relative_to(root) else docs_dir
    lines = [
        f"site_name: {project_name}",
        "theme:",
        "  name: material",
        "nav:",
        "  - Home: index.md",
        "  - Scripts:",
    ]
    for s in sorted(scripts, key=lambda x: str(x.rel_path)):
        lines.append(f"      - {s.title}: {s.stem}.md")
    lines.extend([
        "markdown_extensions:",
        "  - tables",
        "  - fenced_code",
        "  - toc:",
        "      permalink: true",
    ])
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def copy_readme_to_docs_index(root: Path, docs_dir: Path, readme_path: Path) -> None:
    # MkDocs expects docs/index.md. Keep the root README separate and copy the generated content as docs/index.md.
    index = docs_dir / "index.md"
    content = readme_path.read_text(encoding="utf-8")
    # Fix links from docs/index.md to individual docs pages.
    content = re.sub(r"\]\((docs/)([^)]+\.md)\)", r"](\2)", content)
    index.write_text(content, encoding="utf-8")


def backup_if_needed(path: Path, force: bool) -> None:
    if not path.exists() or force:
        return
    backup = path.with_suffix(path.suffix + ".bak")
    counter = 1
    while backup.exists():
        backup = path.with_suffix(path.suffix + f".bak{counter}")
        counter += 1
    path.rename(backup)
    print(f"Backed up existing {path} to {backup}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Generate README.md plus per-script docs/*.md for a Python tooling repo."
    )
    p.add_argument("--repo-root", default=".", help="Repository root to scan. Default: current directory")
    p.add_argument("--docs-dir", default="docs", help="Directory for per-script Markdown files. Default: docs")
    p.add_argument("--readme", default="README.md", help="README path to write. Default: README.md")
    p.add_argument("--project-name", default=None, help="Project title for README/MkDocs. Default: repo directory name")
    p.add_argument("--include-private", action="store_true", help="Include private functions/classes starting with underscore")
    p.add_argument("--exclude", action="append", default=[], help="Additional directory names to exclude. Can be used multiple times")
    p.add_argument("--mkdocs", action="store_true", help="Also create mkdocs.yml and docs/index.md")
    p.add_argument("--force", action="store_true", help="Overwrite README.md/mkdocs.yml without making backups")
    p.add_argument("--dry-run", action="store_true", help="Show what would be generated without writing files")
    args = p.parse_args(argv)

    root = Path(args.repo_root).resolve()
    docs_dir = (root / args.docs_dir).resolve() if not Path(args.docs_dir).is_absolute() else Path(args.docs_dir)
    readme_path = (root / args.readme).resolve() if not Path(args.readme).is_absolute() else Path(args.readme)
    project_name = args.project_name or root.name.replace("_", " ").replace("-", " ").title()
    excludes = set(DEFAULT_EXCLUDES) | set(args.exclude)

    if not root.exists():
        print(f"ERROR: repo root does not exist: {root}", file=sys.stderr)
        return 2

    files = sorted(iter_python_files(root, excludes), key=lambda x: str(x.relative_to(root)))
    files = [f for f in files if f.resolve() != Path(__file__).resolve()]

    scripts = [analyse_script(f, root, include_private=args.include_private) for f in files]
    scripts = [s for s in scripts if not s.syntax_error or s.path.exists()]

    if args.dry_run:
        print(f"Repo root: {root}")
        print(f"Docs dir:  {docs_dir}")
        print(f"README:    {readme_path}")
        print(f"Scripts:   {len(scripts)}")
        for s in scripts:
            print(f"- {s.rel_path} -> {docs_dir / (s.stem + '.md')}")
        return 0

    docs_dir.mkdir(parents=True, exist_ok=True)
    backup_if_needed(readme_path, force=args.force)

    written_docs = []
    for script in scripts:
        written_docs.append(write_script_doc(script, docs_dir, root))

    write_readme(scripts, root, docs_dir, readme_path, project_name)

    if args.mkdocs:
        copy_readme_to_docs_index(root, docs_dir, readme_path)
        mk = write_mkdocs_yml(root, docs_dir, scripts, project_name, force=args.force)
        if mk is None:
            print("mkdocs.yml already exists; use --force to overwrite it")

    print(f"Generated {len(written_docs)} per-script docs in {docs_dir}")
    print(f"Generated README: {readme_path}")
    if args.mkdocs:
        print(f"Generated MkDocs index: {docs_dir / 'index.md'}")
        print("MkDocs command: mkdocs serve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
