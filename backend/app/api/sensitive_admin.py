from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.auth.context import RequestContext, require_role
from app.sensitive.models import SensitiveWordCreate, SensitiveWordListResponse, SensitiveWordResponse, SensitiveWordUpdate
from app.sensitive.automaton import SensitiveEntry


router = APIRouter(prefix="/api/admin/sensitive-words", tags=["sensitive-words"])


def _response(row) -> SensitiveWordResponse:
    return SensitiveWordResponse(
        id=row.id, word=row.word, normalized_word=row.normalized_word, level=row.level,
        category=row.category, enabled=row.enabled, version=row.version, updated_at=row.updated_at,
    )


@router.get("", response_model=SensitiveWordListResponse)
async def list_sensitive_words(
    request: Request,
    context: RequestContext = Depends(require_role("sensitive:read")),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    query: str | None = None,
    level: str | None = None,
    category: str | None = None,
    enabled: bool | None = None,
):
    try:
        parsed_level = __import__("app.core.models", fromlist=["RiskLevel"]).RiskLevel(level) if level else None
        rows, next_cursor, version = await request.app.state.sensitive_repository.list_words(
            context.tenant_id, limit=limit, cursor=cursor, query=query, level=parsed_level, category=category, enabled=enabled
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SensitiveWordListResponse(items=[_response(row) for row in rows], next_cursor=next_cursor, version=version)


@router.post("", response_model=SensitiveWordResponse, status_code=status.HTTP_201_CREATED)
async def create_sensitive_word(request: Request, payload: SensitiveWordCreate, context: RequestContext = Depends(require_role("sensitive:write"))):
    try:
        row = await request.app.state.sensitive_repository.create(context.tenant_id, payload.word, payload.level, payload.category, payload.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await _refresh_tenant(request, context.tenant_id)
    return _response(row)


@router.patch("/{word_id}", response_model=SensitiveWordResponse)
async def update_sensitive_word(request: Request, word_id: str, payload: SensitiveWordUpdate, context: RequestContext = Depends(require_role("sensitive:write"))):
    try:
        row = await request.app.state.sensitive_repository.update(context.tenant_id, word_id, payload.model_dump(exclude_none=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="敏感词不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await _refresh_tenant(request, context.tenant_id)
    return _response(row)


@router.delete("/{word_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sensitive_word(request: Request, word_id: str, context: RequestContext = Depends(require_role("sensitive:write"))):
    await request.app.state.sensitive_repository.delete(context.tenant_id, word_id)
    await _refresh_tenant(request, context.tenant_id)


async def _refresh_tenant(request: Request, tenant_id: str) -> None:
    rows, version = await request.app.state.sensitive_repository.entries(tenant_id)
    request.app.state.sensitive_store.replace_tenant(
        tenant_id,
        [SensitiveEntry(word=row[0], level=__import__("app.core.models", fromlist=["RiskLevel"]).RiskLevel(row[1]), category=row[2], enabled=bool(row[3])) for row in rows],
        version,
    )
