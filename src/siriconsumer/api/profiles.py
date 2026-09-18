from __future__ import annotations

from fastapi import APIRouter, Request

from siriconsumer.api.dependencies import AppServices
from siriconsumer.domain.models import CommunicationProfileInfo

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


def _services(request: Request) -> AppServices:
    return request.app.state.services


@router.get("", response_model=list[CommunicationProfileInfo])
async def list_profiles(request: Request) -> list[CommunicationProfileInfo]:
    return [
        CommunicationProfileInfo(
            profile=profile.profile_id,
            version=profile.version,
            specification=profile.specification,
            supported_services=list(profile.supported_services),
            supported_parameters={
                service: list(parameters)
                for service, parameters in profile.supported_parameters.items()
            },
        )
        for profile in _services(request).profile_registry.list()
    ]
