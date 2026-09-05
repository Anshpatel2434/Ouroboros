"""The local API: interview, refusal, generation, download, publish."""

from __future__ import annotations

import zipfile

import pytest
from fastapi.testclient import TestClient

from ouroboros.corpus.retriever import FileCorpusRetriever
from ouroboros.generator.build import GeneratorDeps
from ouroboros.generator.planner import SkeletonPlan
from ouroboros.generator.review import ReviewReport
from ouroboros.inquisitor.graph import InquisitorDeps
from ouroboros.inquisitor.research import StackPlaybook
from ouroboros.inquisitor.semantic import SemanticReport
from ouroboros.models.blueprint import Backlog
from ouroboros.models.interview import QuestionBatch, SpecDraft
import ouroboros.server.app as app_module
from tests.fakes import FakeLLM
from tests.test_generator import backlog, skeleton
from tests.test_interview import batch, complete_draft, playbook


@pytest.fixture
def client(monkeypatch, tmp_path):
    """A client whose interview and generation both run on scripted models."""
    interview_llm = FakeLLM(
        {
            QuestionBatch: [batch("What problem does this solve?")],
            SpecDraft: [complete_draft()],
            StackPlaybook: [playbook()],
            SemanticReport: [SemanticReport(findings=[])],
        }
    )
    generation_llm = FakeLLM(
        {
            Backlog: [backlog()],
            SkeletonPlan: [skeleton()],
            ReviewReport: [ReviewReport(findings=[], verdict="pass")],
        }
    )

    monkeypatch.setattr(
        app_module,
        "interview_deps",
        lambda: InquisitorDeps(
            llm=interview_llm, retriever=FileCorpusRetriever(), max_rounds=4, corpus_root=tmp_path
        ),
    )
    monkeypatch.setattr(
        app_module,
        "generator_deps",
        lambda: GeneratorDeps(
            llm=generation_llm, critic=generation_llm, retriever=FileCorpusRetriever()
        ),
    )
    app_module.store.sessions.clear()
    app_module.store.generations.clear()
    app_module.store.emitted.clear()
    return TestClient(app_module.app)


def interviewed(client) -> str:
    """Run an interview to completion and return the thread id."""
    started = client.post("/api/interview/start", json={"brief": "An invoice tracker."}).json()
    thread = started["thread_id"]
    client.post(
        f"/api/interview/{thread}/answer",
        json={"answers": [{"question_id": "q1", "value": "Chasing invoices."}]},
    )
    return thread


def test_health_reports_the_corpus_and_model(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["corpus_documents"] == len(FileCorpusRetriever())
    assert body["provider"] in {"groq", "openai", "anthropic"}
    assert body["model"]


def test_interview_start_returns_questions(client):
    body = client.post("/api/interview/start", json={"brief": "An invoice tracker."}).json()
    assert body["status"] == "interviewing"
    assert len(body["questions"]) == 1
    assert body["questions"][0]["why_it_matters"]


def test_interview_reaches_ready(client):
    thread = interviewed(client)
    body = client.get(f"/api/interview/{thread}").json()
    assert body["status"] == "ready"
    assert body["spec"]["name"] == "Invoice Tracker"


def test_generation_is_refused_while_the_spec_is_ambiguous(client):
    """The product's one promise, enforced where it is actually reachable."""
    started = client.post("/api/interview/start", json={"brief": "Something vague."}).json()
    response = client.post(f"/api/generate/{started['thread_id']}")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "refused" in detail["error"].lower()
    assert detail["missing_fields"]


def test_generation_produces_the_harness(client):
    thread = interviewed(client)
    body = client.post(f"/api/generate/{thread}").json()

    assert body["accepted"] is True
    paths = {f["path"] for f in body["files"]}
    assert {"CLAUDE.md", "spec.md", "verify.sh", "task_backlog.json"} <= paths
    assert body["backlog"]["tasks"][0]["id"] == "T-001"


def test_generated_file_can_be_read_back(client):
    thread = interviewed(client)
    client.post(f"/api/generate/{thread}")
    body = client.get(f"/api/generate/{thread}/file", params={"path": "CLAUDE.md"}).json()
    assert "Agent Constitution" in body["contents"]


def test_download_returns_a_usable_zip(client):
    thread = interviewed(client)
    client.post(f"/api/generate/{thread}")
    response = client.get(f"/api/generate/{thread}/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"

    import io

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
    assert "CLAUDE.md" in names and "verify.sh" in names


def test_unknown_session_is_a_404(client):
    assert client.get("/api/interview/nope").status_code == 404
    assert client.post("/api/generate/nope").status_code == 404


def test_publish_requires_an_accepted_repo(client, monkeypatch):
    thread = interviewed(client)
    client.post(f"/api/generate/{thread}")

    result = app_module.store.generations[thread]
    app_module.store.generations[thread] = result.model_copy(
        update={
            "review": ReviewReport(
                findings=[
                    {
                        "location": "verify.sh",
                        "issue": "broken",
                        "evidence": "e",
                        "fix": "f",
                        "blocking": True,
                    }
                ],
                verdict="rejected",
            )
        }
    )

    response = client.post(
        f"/api/publish/{thread}",
        json={"token": "unused", "repo_name": "invoice-tracker", "private": True},
    )
    assert response.status_code == 409
    assert "not accepted" in response.json()["detail"]["error"]
