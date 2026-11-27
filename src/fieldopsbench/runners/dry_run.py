"""Dry-run runner: returns a canned response without calling any model."""

from __future__ import annotations

from ..schema import EvalCase, TraceRecord


class DryRunRunner:
    """Exercises loading, scoring, and reporting. Its scores carry no meaning."""

    name = "dry-run"

    async def run_case(self, case: EvalCase) -> TraceRecord:
        return TraceRecord(
            case_id=case.id,
            final_response="[dry-run] No model was called.",
            model_used="dry-run",
            track="closed_book",
        )
