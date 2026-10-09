"""Evaluate workspace control-plane boundary."""

from fastapi import APIRouter

from app.domains.evaluation_workspace.router import router as _console_router
from app.domains.evaluation_workspace.workload_router import router as _workload_router

router = APIRouter()
router.include_router(_console_router)
router.include_router(_workload_router)

__all__ = ["router"]
