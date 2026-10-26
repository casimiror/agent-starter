"""Evaluation API for the /eval page. Mounted only when EVAL_ENABLED is true (local only)."""

from dataclasses import asdict
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_eval_service
from app.evals.runner import NoRetrieverError
from app.schemas.evals import EvalCapabilities, EvalJobResponse, EvalRunItem, StartEvalRequest
from app.services.eval_service import EvalBusyError, EvalService

router = APIRouter(prefix="/evals", tags=["evals"])

Service = Annotated[EvalService, Depends(get_eval_service)]


@router.get("/capabilities")
def capabilities(service: Service) -> EvalCapabilities:
    """The RAG evaluation exists only when the project has a knowledge tool."""
    return EvalCapabilities(retrieval=service.retrieval_available)


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED)
def start_run(body: StartEvalRequest, service: Service) -> EvalJobResponse:
    try:
        job = service.start(body.kind, body.categories)
    except EvalBusyError:
        raise HTTPException(status.HTTP_409_CONFLICT, "An evaluation is already running.") from None
    except NoRetrieverError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return EvalJobResponse(**asdict(job))


@router.get("/jobs/{job_id}")
def get_job(job_id: str, service: Service) -> EvalJobResponse:
    job = service.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown job.")
    return EvalJobResponse(**asdict(job))


@router.get("/runs")
def list_runs(
    service: Service, kind: Literal["retrieval", "answer"] | None = None
) -> list[EvalRunItem]:
    return [
        EvalRunItem(**run.model_dump(include=set(EvalRunItem.model_fields)))
        for run in service.store.list(kind)
    ]


@router.get("/runs/{run_id}")
def get_run(run_id: str, service: Service) -> dict[str, Any]:
    run = service.store.get(run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown run.")
    return run.model_dump(mode="json")
