---
title: Evaluator-Optimizer Workflow — Generate/Judge Loop with Conditional Edges
source_url: https://docs.langchain.com/oss/python/langgraph/workflows-agents
publisher: LangChain
retrieved: 2026-08-26
domain: orchestration-langgraph
doc_type: official-docs
relevance: Canonical produce→judge→loop-until-pass pattern for the Generator↔Inspector reflection loop and Inquisitor answer refinement.
---

## Summary

The evaluator-optimizer workflow is one of LangGraph's canonical agentic
workflow patterns: one LLM node generates a candidate output, a second LLM node
grades it against explicit criteria using structured output, and a conditional
edge either terminates the graph (pass) or routes back to the generator with the
evaluator's feedback injected into state (fail). The loop is driven entirely by
graph topology — a conditional edge whose branch map points back at the
generator node — and terminates when the graded field in state meets the
acceptance criterion. The docs' worked example is a joke generator/grader, but
the shape is domain-agnostic.

## Key knowledge

- Shared state carries the candidate, the grade, and the feedback:
  ```python
  class State(TypedDict):
      joke: str
      topic: str
      feedback: str
      funny_or_not: str
  ```
- The evaluator uses structured output so routing operates on a typed enum, not prose:
  ```python
  class Feedback(BaseModel):
      grade: Literal["funny", "not funny"] = Field(
          description="Decide if the joke is funny or not.",
      )
      feedback: str = Field(
          description="If the joke is not funny, provide feedback on how to improve it.",
      )

  evaluator = llm.with_structured_output(Feedback)
  ```
- Generator node conditions its prompt on prior feedback (the "optimize" half of the loop):
  ```python
  def llm_call_generator(state: State):
      """LLM generates a joke"""
      if state.get("feedback"):
          msg = llm.invoke(
              f"Write a joke about {state['topic']} but take into account the feedback: {state['feedback']}"
          )
      else:
          msg = llm.invoke(f"Write a joke about {state['topic']}")
      return {"joke": msg.content}
  ```
- Evaluator node writes both the grade and the feedback into state:
  ```python
  def llm_call_evaluator(state: State):
      """LLM evaluates the joke"""
      grade = evaluator.invoke(f"Grade the joke {state['joke']}")
      return {"funny_or_not": grade.grade, "feedback": grade.feedback}
  ```
- The loop is a conditional edge from evaluator back to generator:
  ```python
  def route_joke(state: State):
      """Route back to joke generator or end based upon feedback from the evaluator"""
      if state["funny_or_not"] == "funny":
          return "Accepted"
      elif state["funny_or_not"] == "not funny":
          return "Rejected + Feedback"

  optimizer_builder.add_conditional_edges(
      "llm_call_evaluator",
      route_joke,
      {
          "Accepted": END,
          "Rejected + Feedback": "llm_call_generator",
      },
  )
  ```
  Plus `add_edge(START, "llm_call_generator")` and `add_edge("llm_call_generator", "llm_call_evaluator")` to close the cycle.
- Termination: the docs example ends only when `state["funny_or_not"] == "funny"`. It has no attempt cap — a production loop must add one (standard practice, not in this doc's example): keep an `attempts: int` counter in state, increment in the generator, and have the routing function return the accept branch (or an escalation branch) once `attempts >= max_attempts`. Otherwise the loop is bounded only by the graph-level `recursion_limit` (default 25 supersteps), which raises `GraphRecursionError` rather than exiting gracefully.
- Design points that generalize: (1) separate generator and evaluator into distinct nodes so each gets a focused prompt; (2) the evaluator's structured `grade` field is the router's input — never route on free text; (3) feedback flows to the generator through state, not through conversation history; (4) the pattern fits when there are explicit, checkable success criteria.
- Relation to other patterns on the same page: unlike prompt chaining (fixed linear steps with gates) and orchestrator-worker (dynamic delegation), evaluator-optimizer is the only canonical workflow with an intentional cycle in the graph.

## Notable quotes

> "Evaluator-optimizer workflows are commonly used when there's particular success criteria for a task, but iteration is required to meet that criteria." — LangChain docs

## Application to Ouroboros

- **Inspector:** exactly this shape — the commit-analysis node produces a draft verdict, a judge node grades it against the verdict rubric with `with_structured_output`, and a conditional edge loops until pass or `max_attempts`; the final accepted object is the emitted verdict JSON.
- **Generator:** scaffold output loops through a self-review node (lint/structure critique written into `feedback`) before files are finalized.
- **Inquisitor:** an answer-completeness evaluator can route back to a re-ask node with feedback ("answer lacked X") until the spec field passes, with an attempt cap so interviews never spin.
