from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "asr_provider": settings.asr_provider,
        "device": settings.resolved_device,
        "sensitive_words_path": str(settings.sensitive_words_path),
    }
