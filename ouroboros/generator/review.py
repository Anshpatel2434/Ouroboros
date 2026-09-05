"""The self-review pass — the quality gate on our own output.

A critic model reads the assembled repository and reports what would break an
agent's first session. Blocking findings send the blueprint back for one
correction pass.

Known limit, stated plainly because it matters: a critic can judge whether
`verify.sh` looks right for the stack, but it cannot prove the command runs.
`structural_findings` below covers the mechanical half that judgement should
never have been asked for, and the seam is deliberately wide enough to drop
real execution checking in later.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ouroboros.generator.prompts import SELF_REVIEW
from ouroboros.llm.client import LLM
from ouroboros.models.blueprint import RepoBlueprint


class ReviewFinding(BaseModel):
    location: str = Field(description="File path or task id the finding is about.")
    issue: str
    evidence: str
    fix: str
    blocking: bool = False


class ReviewReport(BaseModel):
    findings: list[ReviewFinding] = Field(default_factory=list)
    verdict: str = "pass"

    @property
    def blocking(self) -> list[ReviewFinding]:
        return [f for f in self.findings if f.blocking]

    @property
    def passed(self) -> bool:
        return not self.blocking

    def summary(self) -> str:
        if self.passed:
            advisory = len(self.findings)
            return f"PASS — {advisory} advisory finding(s)" if advisory else "PASS — clean"
        return f"REJECTED — {len(self.blocking)} blocking finding(s)"


def structural_findings(blueprint: RepoBlueprint) -> list[ReviewFinding]:
    """Mechanical checks on the artifact. No judgement, no model, no arguing."""
    findings: list[ReviewFinding] = []
    paths = set(blueprint.paths())

    required = ["CLAUDE.md", "spec.md", "task_backlog.json", "init.sh", "verify.sh"]
    for path in required:
        if path not in paths:
            findings.append(
                ReviewFinding(
                    location=path,
                    issue="Mandatory harness file missing.",
                    evidence=f"{path} is not in the generated repo.",
                    fix="Emit it; the file inventory is not optional.",
                    blocking=True,
                )
            )

    for task in blueprint.backlog.tasks:
        check_path = f"checks/{task.id}.sh"
        if check_path not in paths:
            findings.append(
                ReviewFinding(
                    location=task.id,
                    issue="Task has no acceptance check.",
                    evidence=f"{check_path} was not generated.",
                    fix="Generate a check script that exits non-zero until the task is done.",
                    blocking=True,
                )
            )
        if not task.scope_paths:
            findings.append(
                ReviewFinding(
                    location=task.id,
                    issue="Task has no scope fence.",
                    evidence=f"{task.id} declares no scope_paths.",
                    fix="Fence the task to the paths its component owns.",
                    blocking=True,
                )
            )
        if not task.done_when:
            findings.append(
                ReviewFinding(
                    location=task.id,
                    issue="Task has no completion condition.",
                    evidence=f"{task.id} declares no done_when.",
                    fix="State observable conditions the check script can evaluate.",
                    blocking=True,
                )
            )

    covered = {t.requirement_id for t in blueprint.backlog.tasks if t.requirement_id}
    for requirement in blueprint.spec.requirements:
        if requirement.id not in covered:
            findings.append(
                ReviewFinding(
                    location=requirement.id,
                    issue="Requirement is not delivered by any task.",
                    evidence=f"No task references {requirement.id}: {requirement.statement}",
                    fix="Add a task for it, or drop the requirement from the spec.",
                    blocking=True,
                )
            )

    # Some files are legitimately empty — a Python package marker, a directory
    # placeholder. Flagging those would train the reader to ignore the check.
    may_be_empty = {"__init__.py", "py.typed", ".gitkeep", ".gitignore", ".keep"}
    empty = [
        f.path
        for f in blueprint.files
        if not f.contents.strip() and f.path.rsplit("/", 1)[-1] not in may_be_empty
    ]
    for path in empty:
        findings.append(
            ReviewFinding(
                location=path,
                issue="Generated file is empty.",
                evidence=f"{path} has no contents.",
                fix="Generate real contents or do not emit the file.",
                blocking=True,
            )
        )

    findings.extend(_manifest_findings(blueprint))
    findings.extend(_undeclared_import_findings(blueprint))
    return findings


def _undeclared_import_findings(blueprint: RepoBlueprint) -> list[ReviewFinding]:
    """Every third-party package the skeleton imports must be declared.

    The manifest and the code are generated by separate calls, so they drift: a
    run produced a cli.py importing click alongside `dependencies = []`. Both
    files look right alone. Together the install provides nothing and the smoke
    command dies on ImportError, which is precisely the "green baseline" the
    skeleton exists to guarantee.
    """
    if blueprint.spec.stack.language.lower() != "python":
        return []

    manifest = next(
        (f for f in blueprint.files if f.path.rsplit("/", 1)[-1] == "pyproject.toml"),
        None,
    )
    if manifest is None:
        return []

    import ast
    import sys
    import tomllib

    try:
        parsed = tomllib.loads(manifest.contents)
    except Exception:  # noqa: BLE001 - a broken manifest is reported elsewhere
        return []

    declared: set[str] = set()
    requirement_lists = [parsed.get("project", {}).get("dependencies", [])]
    requirement_lists += list(parsed.get("dependency-groups", {}).values())
    requirement_lists += list(parsed.get("project", {}).get("optional-dependencies", {}).values())
    for requirements in requirement_lists:
        if not isinstance(requirements, list):
            continue
        for requirement in requirements:
            if isinstance(requirement, str):
                name = re.split(r"[<>=!~\[; ]", requirement.strip(), maxsplit=1)[0]
                declared.add(name.lower().replace("-", "_"))

    # The project's own package is importable without being a dependency.
    own = {blueprint.spec.slug.replace("-", "_").lower()}
    if parsed.get("project", {}).get("name"):
        own.add(str(parsed["project"]["name"]).replace("-", "_").lower())

    imported: dict[str, str] = {}
    for generated in blueprint.files:
        if not generated.path.endswith(".py"):
            continue
        try:
            tree = ast.parse(generated.contents)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.setdefault(alias.name.split(".")[0], generated.path)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.setdefault(node.module.split(".")[0], generated.path)

    stdlib = set(sys.stdlib_module_names)
    findings: list[ReviewFinding] = []
    for module, where in sorted(imported.items()):
        key = module.lower().replace("-", "_")
        if key in stdlib or key in own or key in declared:
            continue
        findings.append(
            ReviewFinding(
                location=where,
                issue=f"Skeleton imports '{module}' but the manifest never declares it.",
                evidence=f"{where} imports {module}; pyproject.toml does not list it.",
                fix=f"Add {module} to [project].dependencies, or drop the import. "
                "Nothing installs it otherwise, so the test and smoke commands "
                "fail on a fresh clone.",
                blocking=True,
            )
        )
    return findings


def _manifest_findings(blueprint: RepoBlueprint) -> list[ReviewFinding]:
    """Check the dependency manifest parses and declares what the stack needs.

    A live run produced a pyproject.toml with no `[project]` table at all: the
    metadata sat under `[tool]` and the dependencies under `[tool.poetry]` in a
    uv project. It is valid TOML and reads plausibly, so the critic passed it —
    but nothing installs, the console script is never created, and verify.sh
    could not have succeeded. Whether a manifest parses is not a judgement call,
    so it belongs in the deterministic half rather than in a prompt.
    """
    findings: list[ReviewFinding] = []

    for generated in blueprint.files:
        name = generated.path.rsplit("/", 1)[-1]

        if name == "pyproject.toml":
            import tomllib

            try:
                parsed = tomllib.loads(generated.contents)
            except Exception as error:  # noqa: BLE001
                findings.append(
                    ReviewFinding(
                        location=generated.path,
                        issue="Dependency manifest is not valid TOML.",
                        evidence=str(error)[:200],
                        fix="Emit a manifest that parses; nothing installs otherwise.",
                        blocking=True,
                    )
                )
                continue

            if "project" not in parsed:
                findings.append(
                    ReviewFinding(
                        location=generated.path,
                        issue="pyproject.toml has no [project] table.",
                        evidence=f"Top-level tables are: {', '.join(parsed) or 'none'}.",
                        fix="Declare name, version, dependencies and scripts under "
                        "[project]. Metadata under [tool] is ignored by installers, "
                        "so the install and smoke commands cannot work.",
                        blocking=True,
                    )
                )
            else:
                findings.extend(_pep621_findings(generated.path, parsed["project"]))

            manager = blueprint.spec.stack.package_manager.lower()
            if "poetry" in parsed.get("tool", {}) and "poetry" not in manager:
                findings.append(
                    ReviewFinding(
                        location=generated.path,
                        issue=f"Manifest mixes Poetry configuration into a {manager} project.",
                        evidence="A [tool.poetry] table is present.",
                        fix=f"Declare dependencies the way {manager} reads them, under "
                        "[project]. Poetry tables are ignored here, so those "
                        "dependencies are never installed.",
                        blocking=True,
                    )
                )

        elif name in {"package.json", "tsconfig.json", "composer.json"}:
            import json

            try:
                json.loads(generated.contents)
            except Exception as error:  # noqa: BLE001
                findings.append(
                    ReviewFinding(
                        location=generated.path,
                        issue=f"{name} is not valid JSON.",
                        evidence=str(error)[:200],
                        fix="Emit a manifest that parses.",
                        blocking=True,
                    )
                )

    return findings


# Modules in the standard library. Declaring one as a dependency fails the
# install, because there is no such package to fetch.
STDLIB_NON_PACKAGES = {
    "sqlite3", "json", "os", "sys", "re", "pathlib", "typing", "asyncio",
    "dataclasses", "subprocess", "logging", "argparse", "datetime", "hashlib",
    "itertools", "functools", "collections", "unittest", "tomllib", "csv",
}


def _pep621_findings(path: str, project: dict) -> list[ReviewFinding]:
    """Validate the shape of a [project] table, not just its presence.

    A generated manifest declared `[project.dependencies]` as a table of
    Poetry-style version constraints. It parses, it has a [project] table, and
    it is still not installable: PEP 621 requires an array of requirement
    strings. Shape is mechanically checkable, so it is checked here.
    """
    findings: list[ReviewFinding] = []

    if not project.get("name"):
        findings.append(
            ReviewFinding(
                location=path,
                issue="[project] declares no name.",
                evidence="project.name is missing or empty.",
                fix="Set project.name to the package name.",
                blocking=True,
            )
        )

    dependencies = project.get("dependencies")
    if dependencies is not None and not isinstance(dependencies, list):
        findings.append(
            ReviewFinding(
                location=path,
                issue="project.dependencies is not an array.",
                evidence=f"It is a {type(dependencies).__name__}: {str(dependencies)[:120]}",
                fix='Use an array of requirement strings, e.g. dependencies = '
                '["click>=8.0"]. A table of version constraints is Poetry syntax '
                "and is not installable here.",
                blocking=True,
            )
        )
    elif isinstance(dependencies, list):
        for requirement in dependencies:
            if not isinstance(requirement, str):
                findings.append(
                    ReviewFinding(
                        location=path,
                        issue="A dependency entry is not a string.",
                        evidence=str(requirement)[:120],
                        fix="Each dependency is one requirement string.",
                        blocking=True,
                    )
                )
                continue
            package = re.split(r"[<>=!~\[; ]", requirement.strip(), maxsplit=1)[0].lower()
            if package in STDLIB_NON_PACKAGES:
                findings.append(
                    ReviewFinding(
                        location=path,
                        issue=f"'{package}' is in the standard library, not a package.",
                        evidence=f"dependencies includes {requirement!r}.",
                        fix=f"Remove it; installing {package} fails because no such "
                        "distribution exists.",
                        blocking=True,
                    )
                )

    authors = project.get("authors")
    if authors is not None and (
        not isinstance(authors, list)
        or any(not isinstance(entry, dict) for entry in authors)
    ):
        findings.append(
            ReviewFinding(
                location=path,
                issue="project.authors has the wrong shape.",
                evidence=str(authors)[:120],
                fix='Use an array of tables, e.g. authors = [{name = "A", '
                'email = "a@example.com"}].',
                blocking=True,
            )
        )

    return findings


# The structural checks already cover the mandatory inventory and the state
# files, so the critic's budget goes to what only judgement can assess: the
# commands that must run, the checks that must prove something, and the
# skeleton that must build.
_LOW_VALUE_FOR_REVIEW = (
    "state/",
    ".gitignore",
    "README.md",
    ".github/",
    "runner/",
    "spec.md",
)


def _review_priority(path: str) -> int:
    if path == "verify.sh" or path == "init.sh":
        return 0
    if path.startswith("checks/"):
        return 1
    if path == "CLAUDE.md":
        return 2
    if path.startswith(_LOW_VALUE_FOR_REVIEW):
        return 9
    return 3  # skeleton files


def _render_for_review(blueprint: RepoBlueprint, budget: int) -> str:
    """The repository as text, most review-worthy files first, inside a budget."""
    ordered = sorted(blueprint.files, key=lambda f: (_review_priority(f.path), f.path))

    chunks: list[str] = []
    remaining = budget
    for generated in ordered:
        if remaining <= 0:
            chunks.append(f"===== {generated.path} ===== [omitted, budget exhausted]")
            continue
        allowance = min(len(generated.contents), max(300, remaining // 3))
        body = generated.contents[:allowance]
        if allowance < len(generated.contents):
            body += "\n... [truncated]"
        chunks.append(f"===== {generated.path} =====\n{body}")
        remaining -= allowance

    return "\n\n".join(chunks)


def _backlog_digest(blueprint: RepoBlueprint) -> str:
    """The backlog as compact lines rather than JSON, which triples the tokens."""
    lines = []
    for task in blueprint.backlog.tasks:
        lines.append(
            f"{task.id} [{task.requirement_id or 'no requirement'}] {task.title}\n"
            f"  scope: {', '.join(task.scope_paths) or 'NONE'}\n"
            f"  done_when: {'; '.join(task.done_when) or 'NONE'}\n"
            f"  depends_on: {', '.join(task.depends_on) or 'none'}"
        )
    return "\n".join(lines) or "(empty backlog)"


def _spec_digest(blueprint: RepoBlueprint) -> str:
    spec = blueprint.spec
    requirements = "\n".join(
        f"  {r.id}: {r.statement} | accepted when: {'; '.join(r.acceptance_criteria)}"
        for r in spec.requirements
    )
    return (
        f"{spec.name} — {spec.one_line}\n"
        f"stack: {spec.stack.language} {spec.stack.language_version}, "
        f"{spec.stack.framework or 'no framework'}, {spec.stack.package_manager}\n"
        f"verification: {', '.join(f'{k}={v}' for k, v in spec.verification.commands())}\n"
        f"non-goals: {'; '.join(spec.non_goals) or 'none'}\n"
        f"requirements:\n{requirements}"
    )


def self_review(llm: LLM, blueprint: RepoBlueprint) -> ReviewReport:
    """Structural checks first, then the critic on what survives."""
    from ouroboros.llm.client import context_chars

    structural = structural_findings(blueprint)

    report = llm.structured(
        ReviewReport,
        system=SELF_REVIEW,
        user=(
            f"Specification:\n{_spec_digest(blueprint)}\n\n"
            f"Backlog:\n{_backlog_digest(blueprint)}\n\n"
            f"Generated repository:\n"
            + _render_for_review(blueprint, context_chars("review"))
        ),
        role="review",
    )

    combined = structural + report.findings
    return ReviewReport(
        findings=combined,
        verdict="pass" if not any(f.blocking for f in combined) else "rejected",
    )
