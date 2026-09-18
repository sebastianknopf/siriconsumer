from __future__ import annotations

import httpx

from siriconsumer.domain.models import SubscriptionRecord
from siriconsumer.interfaces.intf_communication_monitor import CommunicationMonitor
from siriconsumer.interfaces.intf_profile import CommunicationProfile, PublisherAction
from siriconsumer.interfaces.intf_siri_client import ProviderStatus
from siriconsumer.profiles.registry import ProfileRegistry


class SiriHttpClient:
    def __init__(
        self,
        timeout_seconds: float = 20.0,
        *,
        communication_monitor: CommunicationMonitor | None = None,
        profile_registry: ProfileRegistry | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(timeout=timeout_seconds)
        self._communication_monitor = communication_monitor
        self._profile_registry = profile_registry or ProfileRegistry()

    async def close(self) -> None:
        await self._client.aclose()

    async def subscribe(self, subscription: SubscriptionRecord) -> None:
        profile = self._profile(subscription)
        payload = profile.build_subscription_request(subscription)
        response = await self._post(
            subscription,
            PublisherAction.SUBSCRIBE,
            payload,
        )
        response.raise_for_status()
        profile.validate_subscription_response(response.content)

    async def terminate(self, subscription: SubscriptionRecord) -> None:
        profile = self._profile(subscription)
        payload = profile.build_termination_request(subscription)
        response = await self._post(
            subscription,
            PublisherAction.TERMINATE,
            payload,
        )
        if response.status_code == 404:
            return
        response.raise_for_status()

    async def check_status(self, subscription: SubscriptionRecord) -> ProviderStatus:
        profile = self._profile(subscription)
        payload = profile.build_check_status_request(subscription)
        response = await self._post(
            subscription,
            PublisherAction.CHECK_STATUS,
            payload,
        )
        response.raise_for_status()
        return profile.parse_provider_status(response.content)

    async def fetch_delivery(self, subscription: SubscriptionRecord) -> bytes:
        profile = self._profile(subscription)
        payload = profile.build_data_supply_request(subscription)
        response = await self._post(
            subscription,
            PublisherAction.FETCH_DELIVERY,
            payload,
        )
        response.raise_for_status()
        return response.content

    async def _post(
        self,
        subscription: SubscriptionRecord,
        action: PublisherAction,
        payload: bytes,
    ) -> httpx.Response:
        headers = {"Content-Type": "application/xml"}
        for name, value in subscription.config.headers.items():
            for existing_name in list(headers):
                if existing_name.lower() == name.lower():
                    del headers[existing_name]
            headers[name] = value

        profile = self._profile(subscription)
        endpoint = profile.resolve_endpoint(action, subscription)
        if self._communication_monitor is not None:
            self._communication_monitor.publish(
                direction="outgoing",
                kind="request",
                payload=payload,
                endpoint=endpoint,
            )

        response = await self._client.post(endpoint, content=payload, headers=headers)
        if self._communication_monitor is not None:
            self._communication_monitor.publish(
                direction="incoming",
                kind="response",
                payload=response.content,
                endpoint=endpoint,
                status_code=response.status_code,
            )

        return response

    def _profile(self, subscription: SubscriptionRecord) -> CommunicationProfile:
        return self._profile_registry.get(subscription.config.profile, subscription.config.version)

    def _build_subscription_request(self, subscription: SubscriptionRecord) -> bytes:
        return self._profile(subscription).build_subscription_request(subscription)
