"""Repairing a generated Python manifest instead of asking for it again.

Models keep writing dependencies as a table of version constraints —
`[project.dependencies]` with `click = "^8.0"` — which is Poetry syntax that
PEP 621 tooling ignores entirely. The structural check catches it, the
correction pass is told exactly what is wrong, and the next attempt writes the
same table again; a developer ends up with a rejected repo after a whole
interview.

The conversion is mechanical. A table of name-to-constraint pairs is an array of
requirement strings, and we know it. So it is fixed here rather than re-requested,
for the same reason verification commands are filled from a researched playbook:
never spend a model call on something already determined.
"""

from __future__ import annotations

import re
import tomllib

# Poetry's caret and tilde both mean "at least this", which is the part PEP 621
# can express. Narrowing further would invent a constraint nobody asked for.
_CONSTRAINT = re.compile(r"^[\^~]\s*")


def _requirement(name: str, constraint: object) -> str | None:
    """One PEP 621 requirement string from a table entry."""
    if name.strip().lower() == "python":
        return None  # Expressed as requires-python, never as a dependency.
    if not isinstance(constraint, str) or not constraint.strip() or constraint.strip() == "*":
        return name
    text = _CONSTRAINT.sub(">=", constraint.strip())
    if text[0].isdigit():
        text = f">={text}"
    return f"{name}{text}"


def _strip_table(text: str, header: str) -> str:
    """Remove one `[header]` table and its entries, leaving the rest untouched."""
    lines = text.splitlines()
    kept: list[str] = []
    dropping = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            dropping = stripped in (f"[{header}]", f'["{header}"]')
        if not dropping:
            kept.append(line)
    return "\n".join(kept)


def normalise_pyproject(text: str) -> tuple[str, str | None]:
    """Return (manifest, note). The note says what was repaired, if anything."""
    try:
        parsed = tomllib.loads(text)
    except Exception:  # noqa: BLE001 - an unparseable manifest is reported elsewhere
        return text, None

    project = parsed.get("project")
    if not isinstance(project, dict):
        return text, None

    declared = project.get("dependencies")
    poetry = parsed.get("tool", {}).get("poetry", {}).get("dependencies")

    if isinstance(declared, dict):
        source, table = declared, "project.dependencies"
    elif declared is None and isinstance(poetry, dict):
        source, table = poetry, "tool.poetry.dependencies"
    else:
        return text, None

    requirements = [
        requirement
        for name, constraint in source.items()
        if (requirement := _requirement(str(name), constraint))
    ]

    rewritten = _strip_table(text, table)
    array = ", ".join(f'"{r}"' for r in requirements)
    inserted = f"dependencies = [{array}]"

    lines = rewritten.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == "[project]":
            lines.insert(index + 1, inserted)
            break
    else:
        return text, None

    note = (
        f"Rewrote [{table}] as a PEP 621 dependencies array "
        f"({len(requirements)} package(s)); a table of version constraints "
        "installs nothing."
    )
    return "\n".join(lines) + "\n", note
