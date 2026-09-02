"""The local API the web UI talks to.

Local-only by design: it binds to localhost, holds sessions in memory, and never
persists a GitHub token. There is no auth because there is no remote — if this
ever grows a hosted deployment, that assumption has to be revisited first.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ouroboros.generator.build import GenerationResult, GeneratorDeps, emit, generate
from ouroboros.inquisitor.graph import InquisitorDeps, InterviewSession
from ouroboros.models.spec import ProjectSpec
from ouroboros.publish.github import PublishError, publish, zip_directory

app = FastAPI(title="Ouroboros", version="0.1.0")

# The UI runs on its own port, and Next picks the next free one when 3000 is
# taken, so the origin is matched by pattern. Localhost only either way.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)


class _Store:
    """In-memory session state. Local single-user tool; a restart clears it."""

    def __init__(self) -> None:
        self.sessions: dict[str, InterviewSession] = {}
        self.generations: dict[str, GenerationResult] = {}
        self.emitted: dict[str, Path] = {}

    def session(self, thread_id: str) -> InterviewSession:
        session = self.sessions.get(thread_id)
        if session is None:
            raise HTTPException(404, f"No interview session '{thread_id}'.")
        return session

    def generation(self, thread_id: str) -> GenerationResult:
        result = self.generations.get(thread_id)
        if result is None:
            raise HTTPException(404, "Nothing generated for this session yet.")
        return result


store = _Store()


def interview_deps() -> InquisitorDeps:
    return InquisitorDeps()


def generator_deps() -> GeneratorDeps:
    return GeneratorDeps()


# --------------------------------------------------------------------------- #
# Interview
# --------------------------------------------------------------------------- #

class StartRequest(BaseModel):
    brief: str = Field(min_length=1, description="What the developer wants to build.")


class AnswerRequest(BaseModel):
    answers: list[dict[str, str]] = Field(default_factory=list)


@app.post("/api/interview/start")
def start_interview(request: StartRequest) -> dict[str, Any]:
    thread_id = uuid.uuid4().hex[:12]
    session = InterviewSession(thread_id, deps=interview_deps())
    store.sessions[thread_id] = session
    try:
        return session.start(request.brief)
    except Exception as error:  # noqa: BLE001 - surfaced to the UI verbatim
        store.sessions.pop(thread_id, None)
        raise HTTPException(502, f"The interviewer failed to start: {error}") from None


@app.post("/api/interview/{thread_id}/answer")
def answer_interview(thread_id: str, request: AnswerRequest) -> dict[str, Any]:
    session = store.session(thread_id)
    try:
        return session.answer(request.answers)
    except Exception as error:  # noqa: BLE001
        raise HTTPException(502, f"The interviewer failed: {error}") from None


@app.get("/api/interview/{thread_id}")
def get_interview(thread_id: str) -> dict[str, Any]:
    return store.session(thread_id).snapshot()


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #

@app.post("/api/generate/{thread_id}")
def generate_repo(thread_id: str) -> dict[str, Any]:
    snapshot = store.session(thread_id).snapshot()

    if snapshot["status"] != "ready" or not snapshot["spec"]:
        # This is the product's one promise, enforced at the only place that matters.
        raise HTTPException(
            409,
            {
                "error": "Generation refused: the specification is not unambiguous yet.",
                "lint": snapshot.get("lint"),
                "missing_fields": snapshot.get("missing_fields", []),
            },
        )

    spec = ProjectSpec.model_validate(snapshot["spec"])
    try:
        result = generate(spec, generator_deps())
    except Exception as error:  # noqa: BLE001
        raise HTTPException(502, f"Generation failed: {error}") from None

    store.generations[thread_id] = result
    destination = Path(tempfile.mkdtemp(prefix=f"ouroboros-{spec.slug}-"))
    emit(result.blueprint, destination)
    store.emitted[thread_id] = destination

    return {
        "accepted": result.accepted,
        "attempts": result.attempts,
        "review": result.review.model_dump(mode="json"),
        "review_summary": result.review.summary(),
        "notes": result.blueprint.notes,
        "backlog": result.blueprint.backlog.model_dump(mode="json"),
        "files": [
            {"path": f.path, "bytes": len(f.contents), "executable": f.executable}
            for f in result.blueprint.files
        ],
        "output_dir": str(destination),
    }


@app.get("/api/generate/{thread_id}/file")
def read_generated_file(thread_id: str, path: str) -> dict[str, Any]:
    generated = store.generation(thread_id).blueprint.file(path)
    if generated is None:
        raise HTTPException(404, f"No generated file '{path}'.")
    return {"path": generated.path, "contents": generated.contents}


@app.get("/api/generate/{thread_id}/download")
def download_repo(thread_id: str) -> Response:
    store.generation(thread_id)
    directory = store.emitted.get(thread_id)
    if directory is None:
        raise HTTPException(404, "Nothing emitted for this session.")

    slug = store.generation(thread_id).blueprint.spec.slug
    return Response(
        content=zip_directory(directory),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{slug}-harness.zip"'},
    )


# --------------------------------------------------------------------------- #
# Publish
# --------------------------------------------------------------------------- #

class PublishRequest(BaseModel):
    token: str = Field(min_length=1, description="Fine-grained PAT. Never stored.")
    repo_name: str = Field(min_length=1)
    private: bool = True


@app.post("/api/publish/{thread_id}")
def publish_repo(thread_id: str, request: PublishRequest) -> dict[str, Any]:
    result = store.generation(thread_id)
    directory = store.emitted.get(thread_id)
    if directory is None:
        raise HTTPException(404, "Nothing emitted for this session.")

    if not result.accepted:
        raise HTTPException(
            409,
            {
                "error": "This repo was not accepted by review. Fix the findings before publishing.",
                "review": result.review.model_dump(mode="json"),
            },
        )

    try:
        published = publish(directory, request.token, request.repo_name, private=request.private)
    except PublishError as error:
        raise HTTPException(502, str(error)) from None

    return {
        "repo_url": published.repo_url,
        "clone_url": published.clone_url,
        "branch": published.branch,
        "created": published.created,
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    from ouroboros.corpus.retriever import FileCorpusRetriever

    return {"status": "ok", "corpus_documents": len(FileCorpusRetriever())}
