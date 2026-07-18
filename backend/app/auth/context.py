from __future__ import annotations

from dataclasses import dataclass
import uuid

import jwt
from fastapi import Depends, HTTPException, Request, status


@dataclass(frozen=True, slots=True)
class RequestContext:
    user_id: str
    tenant_id: str
    roles: frozenset[str]


async def current_context(request: Request) -> RequestContext:
    settings = request.app.state.settings
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    if not settings.auth_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="认证服务未配置")
    try:
        payload = jwt.decode(
            authorization[7:],
            settings.auth_secret,
            algorithms=["HS256"],
            audience=settings.auth_audience or None,
            issuer=settings.auth_issuer or None,
            options={"verify_aud": bool(settings.auth_audience), "verify_iss": bool(settings.auth_issuer)},
        )
        user_id = str(payload["sub"])
        tenant_id = str(payload["tenant_id"])
        uuid.UUID(tenant_id)
        roles = frozenset(str(role) for role in payload.get("roles", []))
    except (KeyError, ValueError, jwt.PyJWTError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="身份令牌无效") from exc
    requested_tenant = request.headers.get("X-Tenant-Id")
    if requested_tenant and requested_tenant != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="禁止跨租户访问")
    return RequestContext(user_id, tenant_id, roles)


def require_role(role: str):
    async def dependency(context: RequestContext = Depends(current_context)) -> RequestContext:
        if role not in context.roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="没有敏感词管理权限")
        return context

    return dependency
