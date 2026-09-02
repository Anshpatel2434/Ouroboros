"""The ProjectSpec contract.

This is the central artifact of Ouroboros. The Inquisitor fills it in through
interview, the ambiguity lint gates it, and the Generator consumes it to emit a
harness repo. Every field exists because something downstream needs it; nothing
here is decorative.

A spec that passes the lint must be complete enough that the Generator never has
to guess.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Topology(str, Enum):
    """How the generated runner drives the coding agent (spec decision D10)."""

    DRIVER_LOOP = "driver_loop"
    WORKTREE_FLEET = "worktree_fleet"


class Requirement(BaseModel):
    """One thing the software must do, with machine-checkable acceptance.

    Acceptance criteria are what `checks/` scripts are generated from, so they
    must describe observable behaviour, not intent.
    """

    id: str = Field(description="Stable identifier, e.g. 'R-004'.")
    statement: str = Field(description="What the system must do, one sentence.")
    acceptance_criteria: list[str] = Field(
        default_factory=list,
        description="Observable, verifiable conditions that prove the requirement is met.",
    )
    priority: Literal["must", "should"] = "must"
    depends_on: list[str] = Field(
        default_factory=list, description="Requirement ids that must land first."
    )


class Component(BaseModel):
    """A named part of the system the agent will build."""

    name: str
    responsibility: str = Field(description="What this component is for, one sentence.")
    paths: list[str] = Field(
        default_factory=list,
        description="Files/directories it owns. Becomes the task scope fence.",
    )


class VerificationPlan(BaseModel):
    """The commands that decide whether the agent's work is acceptable.

    These are the single most important fields in the spec: `verify.sh` is built
    from them, and the agent's entire feedback loop depends on them being real,
    runnable commands for the chosen stack.
    """

    install: str = Field(description="Install dependencies, e.g. 'npm ci'.")
    test: str = Field(description="Run the test suite, e.g. 'pytest -q'.")
    lint: str | None = None
    typecheck: str | None = None
    build: str | None = None
    smoke: str | None = Field(
        default=None,
        description="Cheapest end-to-end proof the app runs at all.",
    )

    def commands(self) -> list[tuple[str, str]]:
        """Ordered (label, command) pairs for rendering into verify.sh."""
        ordered = [
            ("install", self.install),
            ("lint", self.lint),
            ("typecheck", self.typecheck),
            ("build", self.build),
            ("test", self.test),
            ("smoke", self.smoke),
        ]
        return [(label, cmd) for label, cmd in ordered if cmd]


class StackProfile(BaseModel):
    """The concrete technology the harness must be correct for."""

    language: str = Field(description="e.g. 'TypeScript', 'Python', 'Go'.")
    language_version: str = Field(description="e.g. '3.12', '22.x'.")
    framework: str | None = None
    package_manager: str = Field(description="e.g. 'pnpm', 'uv', 'cargo'.")
    database: str | None = None
    key_libraries: list[str] = Field(default_factory=list)
    corpus_covered: bool = Field(
        default=False,
        description="False means gap research must run before generation (D7/D9).",
    )


class LoopBoundaries(BaseModel):
    """The hard walls of the generated runner (spec decision D14)."""

    topology: Topology = Topology.DRIVER_LOOP
    max_attempts_per_task: int = Field(default=3, ge=1)
    max_wall_clock_minutes: int = Field(default=480, ge=1)
    max_cost_usd: float | None = None
    protected_paths: list[str] = Field(
        default_factory=lambda: [
            "CLAUDE.md",
            "spec.md",
            "verify.sh",
            "checks/",
            ".githooks/",
        ],
        description="Agent edits here are an automatic critical violation (D17).",
    )


class ProjectSpec(BaseModel):
    """The complete, interview-derived description of what to build."""

    name: str
    slug: str = Field(description="Repo-safe name, kebab-case.")
    one_line: str = Field(description="What this project is, in one sentence.")

    problem: str = Field(description="The problem being solved, and for whom.")
    success_criteria: list[str] = Field(
        default_factory=list,
        description="How we know the finished project succeeded.",
    )
    non_goals: list[str] = Field(
        default_factory=list,
        description="Explicitly out of scope. Prevents agent scope creep.",
    )

    stack: StackProfile
    verification: VerificationPlan
    components: list[Component] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    boundaries: LoopBoundaries = Field(default_factory=LoopBoundaries)

    glossary: dict[str, str] = Field(
        default_factory=dict,
        description="Domain terms and their definitions. Undefined terms fail the lint.",
    )
    open_questions: list[str] = Field(
        default_factory=list,
        description="Unresolved points. Must be empty before generation (D6).",
    )

    def requirement_ids(self) -> set[str]:
        return {r.id for r in self.requirements}
