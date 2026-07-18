from fastapi import APIRouter, Depends, Request

from app.auth.context import RequestContext, require_role

router = APIRouter(prefix="/api/pbx/calls", tags=["pbx-calls"])


@router.get("", dependencies=[Depends(require_role("calls:read"))])
async def list_calls(request: Request, context: RequestContext = Depends(require_role("calls:read"))):
    rows = await request.app.state.pbx_calls.list(context.tenant_id)
    keys = ("id", "tenant_id", "source", "source_session_id", "status", "started_at", "updated_at", "customer_number", "sales_number", "role_pending", "media_interrupted", "asr_degraded")
    return {"items": [dict(zip(keys, row, strict=True)) for row in rows], "next_cursor": None}
