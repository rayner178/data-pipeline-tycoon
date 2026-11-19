"""FastAPI routers: input validation, use-case delegation and DTO serialization."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from api.auth import require_api_key
from api.dependencies import (
    get_list_challenges_use_case,
    get_progress_use_case,
    get_submit_solution_use_case,
)
from api.schemas import (
    ChallengeSummaryResponse,
    CompletedChallengeResponse,
    ErrorResponse,
    HealthResponse,
    PlayerProgressResponse,
    SubmitSolutionRequest,
    SubmitSolutionResponse,
)
from application.use_cases.get_progress import GetProgress
from application.use_cases.list_challenges import ListChallenges
from application.use_cases.submit_solution import SubmitSolution

health_router = APIRouter(tags=["health"])
api_router = APIRouter(
    dependencies=[Depends(require_api_key)],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
)


@health_router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    return HealthResponse()


@api_router.get("/challenges", response_model=list[ChallengeSummaryResponse])
def list_challenges(
    use_case: Annotated[ListChallenges, Depends(get_list_challenges_use_case)],
) -> list[ChallengeSummaryResponse]:
    summaries = use_case.execute()
    return [
        ChallengeSummaryResponse(
            code=item.code,
            module=item.module,
            title=item.title,
            description=item.description,
            difficulty=int(item.difficulty),
        )
        for item in summaries
    ]


@api_router.post(
    "/challenges/{code}/submit",
    response_model=SubmitSolutionResponse,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def submit_solution(
    code: str,
    body: SubmitSolutionRequest,
    use_case: Annotated[SubmitSolution, Depends(get_submit_solution_use_case)],
) -> SubmitSolutionResponse:
    result = use_case.execute(
        roblox_user_id=body.roblox_user_id,
        code=code,
        sql=body.sql,
    )
    return SubmitSolutionResponse(
        passed=result.passed,
        execution_ms=result.execution_ms,
        message=result.message,
    )


@api_router.get(
    "/players/{roblox_user_id}/progress",
    response_model=PlayerProgressResponse,
)
def get_player_progress(
    roblox_user_id: Annotated[int, Path(gt=0)],
    use_case: Annotated[GetProgress, Depends(get_progress_use_case)],
) -> PlayerProgressResponse:
    progress = use_case.execute(roblox_user_id)
    return PlayerProgressResponse(
        roblox_user_id=progress.roblox_user_id,
        completed=[
            CompletedChallengeResponse(
                code=item.code,
                completed_at=item.completed_at,
                best_ms=item.best_ms,
            )
            for item in progress.completed
        ],
    )
