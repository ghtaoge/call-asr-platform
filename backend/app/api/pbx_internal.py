from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.pbx.models import PbxCallStart, PbxCallStatus

router = APIRouter(prefix="/api/internal/pbx", tags=["pbx-internal"])


async def verify_gateway(request: Request, x_gateway_token: str | None = Header(default=None)):
    if not request.app.state.settings.pbx_internal_token or x_gateway_token != request.app.state.settings.pbx_internal_token:
        raise HTTPException(status_code=401, detail="网关身份无效")


@router.post("/calls/start", dependencies=[Depends(verify_gateway)])
async def start_call(request: Request, payload: PbxCallStart):
    row = await request.app.state.pbx_calls.start(request.headers.get("X-Tenant-Id", "default"), payload)
    return _response(row)


@router.post("/calls/{source_session_id}/status", dependencies=[Depends(verify_gateway)])
async def update_call(request: Request, source_session_id: str, payload: PbxCallStatus):
    row = await request.app.state.pbx_calls.update(request.headers.get("X-Tenant-Id", "default"), source_session_id, payload)
    if not row: raise HTTPException(status_code=404, detail="通话不存在")
    return _response(row)


def _response(row):
    keys = ("id", "tenant_id", "source", "source_session_id", "status", "started_at", "updated_at", "customer_number", "sales_number", "role_pending", "media_interrupted", "asr_degraded")
    return dict(zip(keys, row, strict=True))
