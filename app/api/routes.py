"""API-роуты для управления задачами."""

from __future__ import annotations

import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.queue import (
    cancel_task,
    create_task,
    get_cached_result,
    get_task,
    list_tasks,
    check_rate_limit_api,
)
from app.schemas.task import (
    TaskCreate,
    TaskListResponse,
    TaskResponse,
    TaskStatusResponse,
)
from app.utils.logger import get_logger

log = get_logger("routes")

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskStatusResponse, status_code=201)
async def create_task_endpoint(task_data: TaskCreate) -> TaskStatusResponse:
    """Создать задачу и поместить в очередь."""
    allowed = await check_rate_limit_api()
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    try:
        task = await create_task(task_data.type, task_data.payload)
        return TaskStatusResponse(id=task.id, status=task.status, retries=task.retries)
    except Exception as e:
        log.error("create_task_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=TaskListResponse)
async def list_tasks_endpoint(limit: int = 20, offset: int = 0) -> TaskListResponse:
    """Возвращает список задач с пагинацией."""
    tasks, total = await list_tasks(limit=limit, offset=offset)
    items = [
        TaskResponse(
            id=t.id,
            type=t.type,
            status=t.status,
            payload=t.payload,
            result=t.result,
            error=t.error,
            retries=t.retries,
            max_retries=t.max_retries,
            created_at=t.created_at,
            updated_at=t.updated_at,
            started_at=t.started_at,
            finished_at=t.finished_at,
        )
        for t in tasks
    ]
    return TaskListResponse(total=total, items=items)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task_endpoint(task_id: str) -> TaskResponse:
    """Возвращает задачу по ID с проверкой кэша."""
    task = await get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    result = task.result
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            result = None

    return TaskResponse(
        id=task.id,
        type=task.type,
        status=task.status,
        payload=task.payload,
        result=result,
        error=task.error,
        retries=task.retries,
        max_retries=task.max_retries,
        created_at=task.created_at,
        updated_at=task.updated_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
    )


@router.delete("/{task_id}", response_model=TaskStatusResponse)
async def cancel_task_endpoint(task_id: str) -> TaskStatusResponse:
    """Отменяет задачу."""
    try:
        task = await cancel_task(task_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskStatusResponse(id=task.id, status=task.status, retries=task.retries)


__all__ = ["router"]