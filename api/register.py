from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.support import require_admin
from services.register_service import register_service


class RegisterConfigRequest(BaseModel):
    mail: dict | None = None
    scheduler: dict | None = None
    proxy: str | None = None
    proxy_mode: str | None = None
    mihomo: dict | None = None
    mimo: dict | None = None
    total: int | None = None
    threads: int | None = None
    mode: str | None = None
    target_quota: int | None = None
    target_available: int | None = None
    check_interval: int | None = None


class OutlookPoolResetRequest(BaseModel):
    scope: str | None = None


class QueueImportRequest(BaseModel):
    text: str = ""


class QueueRemoveRequest(BaseModel):
    ids: list[str] = []


class QueueClearRequest(BaseModel):
    scope: str | None = None


class FailedRetryRequest(BaseModel):
    ids: list[str] | None = None
    mode: str | None = None


def _service_call(fn, *args):
    try:
        return {"register": fn(*args)}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/register")
    async def get_register_config(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.get()}

    @router.post("/api/register")
    async def update_register_config(body: RegisterConfigRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.update(body.model_dump(exclude_none=True))}

    @router.post("/api/register/queue/import")
    async def import_register_queue(body: QueueImportRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return _service_call(register_service.import_queue, body.text)

    @router.post("/api/register/queue/remove")
    async def remove_register_queue(body: QueueRemoveRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return _service_call(register_service.remove_queue, body.ids)

    @router.post("/api/register/queue/clear")
    async def clear_register_queue(body: QueueClearRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return _service_call(register_service.clear_queue, body.scope or "all")

    @router.post("/api/register/failed/retry")
    async def retry_failed_register(body: FailedRetryRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return _service_call(register_service.retry_failed, body.ids or [], body.mode or "auto")

    @router.post("/api/register/failed/remove")
    async def remove_failed_register(body: QueueRemoveRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return _service_call(register_service.remove_failed, body.ids)

    @router.post("/api/register/failed/clear")
    async def clear_failed_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return _service_call(register_service.clear_failed)

    @router.post("/api/register/recovery/import")
    async def import_login_recovery(body: QueueImportRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return _service_call(register_service.queue_login_recovery, body.text)

    @router.post("/api/register/proxy/refresh")
    async def refresh_register_proxy(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return _service_call(register_service.refresh_proxy)

    @router.post("/api/register/proxy/stop")
    async def stop_register_proxy(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return _service_call(register_service.stop_proxy)

    @router.post("/api/register/start")
    async def start_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.start()}

    @router.post("/api/register/stop")
    async def stop_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.stop()}

    @router.post("/api/register/reset")
    async def reset_register(authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.reset()}

    @router.post("/api/register/outlook-pool/reset")
    async def reset_outlook_pool(body: OutlookPoolResetRequest, authorization: str | None = Header(default=None)):
        require_admin(authorization)
        return {"register": register_service.reset_outlook_pool(body.scope or "all")}

    @router.get("/api/register/events")
    async def register_events(token: str = ""):
        require_admin(f"Bearer {token}")

        async def stream():
            last = ""
            while True:
                payload = json.dumps(register_service.get(), ensure_ascii=False)
                if payload != last:
                    last = payload
                    yield f"data: {payload}\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(stream(), media_type="text/event-stream")

    return router
