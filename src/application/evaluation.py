"""Evidence returned by a SolutionEvaluator.

The evaluator does not decide whether a challenge is passed; it reports what
happened and SubmitSolution applies the domain rules. Fields are keyword-only so
new evidence can be added with a default value without breaking callers.
"""

from dataclasses import dataclass

from domain.result_matching import FrozenResult


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionSucceeded:
    """The player's SQL ran; ``rows`` is its result."""

    rows: FrozenResult
    execution_ms: int
    columns: tuple[str, ...] = ()
    plan: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionFailed:
    """The player's SQL failed (syntax, timeout, permission...).

    ``error_message`` must already be sanitized by the adapter (phase 5).
    """

    error_message: str
    execution_ms: int | None = None


type EvaluationResult = ExecutionSucceeded | ExecutionFailed
