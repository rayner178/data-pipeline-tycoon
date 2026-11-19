"""Application errors. Framework-free: the API layer maps them to responses."""


class ApplicationError(Exception):
    """Base class for errors that callers of the use cases are expected to handle."""


class EmptySubmission(ApplicationError):
    def __init__(self) -> None:
        super().__init__("the submitted SQL is empty")


class ChallengeNotFound(ApplicationError):
    def __init__(self, code: str) -> None:
        super().__init__(f"challenge not found: {code}")
        self.code = code


class EvaluatorUnavailable(ApplicationError):
    def __init__(self) -> None:
        super().__init__("the solution evaluator is unavailable")


class EvaluatorError(Exception):
    """Infrastructure failure inside a SolutionEvaluator adapter.

    Part of the SolutionEvaluator port contract: adapters raise only this
    exception for infrastructure problems. It is not an ApplicationError because
    callers never see it; SubmitSolution translates it into EvaluatorUnavailable.
    """
