"""What the Generator produces before anything touches a disk.

A blueprint is the whole repository held in memory: every file, its contents,
and the backlog the agent will work through. Keeping it in memory first means
the self-review critiques the real artifact, and a rejected generation never
leaves a half-written repo behind.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ouroboros.models.spec import ProjectSpec


class GeneratedFile(BaseModel):
    path: str
    contents: str
    executable: bool = False


class Task(BaseModel):
    """One unit of agent work: a single commit, with its own proof (D5)."""

    id: str
    title: str
    requirement_id: str | None = None
    intent: str = Field(description="What this task must achieve, for the agent.")
    scope_paths: list[str] = Field(
        default_factory=list,
        description="The only paths this task may touch. Enforced by the pre-commit hook.",
    )
    done_when: list[str] = Field(
        default_factory=list, description="Observable conditions proving the task is done."
    )
    check_script: str = Field(
        default="", description="Body of checks/<id>.sh — must exit non-zero when unmet."
    )
    depends_on: list[str] = Field(default_factory=list)
    status: str = "pending"
    attempts: int = 0


class Backlog(BaseModel):
    tasks: list[Task] = Field(default_factory=list)

    def ids(self) -> set[str]:
        return {t.id for t in self.tasks}


class RepoBlueprint(BaseModel):
    """A complete generated repository, not yet written to disk."""

    spec: ProjectSpec
    backlog: Backlog
    files: list[GeneratedFile] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def paths(self) -> list[str]:
        return [f.path for f in self.files]

    def file(self, path: str) -> GeneratedFile | None:
        return next((f for f in self.files if f.path == path), None)
