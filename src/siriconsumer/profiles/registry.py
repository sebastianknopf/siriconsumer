from __future__ import annotations

from siriconsumer.interfaces.intf_profile import CommunicationProfile
from siriconsumer.profiles.de_vdv_2 import GermanVdv2Profile
from siriconsumer.profiles.default import DefaultSiriProfile


class UnknownProfileError(ValueError):
    """Raised when a subscription references an unsupported profile/version pair."""


class ProfileRegistry:
    def __init__(self, profiles: list[CommunicationProfile] | None = None) -> None:
        configured = profiles or [DefaultSiriProfile(), GermanVdv2Profile()]
        self._profiles = {
            (profile.profile_id, profile.version): profile
            for profile in configured
        }

    def get(self, profile_id: str, version: str = "default") -> CommunicationProfile:
        try:
            return self._profiles[(profile_id, version)]
        except KeyError as exc:
            raise UnknownProfileError(
                f"Unknown communication profile '{profile_id}' version '{version}'"
            ) from exc

    def list(self) -> list[CommunicationProfile]:
        return list(self._profiles.values())
