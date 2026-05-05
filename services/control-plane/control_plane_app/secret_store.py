from __future__ import annotations

import json
from typing import Any, Protocol
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .config import Settings


class SecretStoreError(RuntimeError):
    pass


class SecretNotFoundError(SecretStoreError):
    pass


class SecretStoreProvider(Protocol):
    kind: str

    def store_secret(
        self,
        *,
        tenant_id: str,
        secret: dict[str, Any],
        secret_id: str | None = None,
    ) -> str:
        ...

    def get_secret(
        self,
        *,
        tenant_id: str,
        provider_ref: str,
    ) -> dict[str, Any]:
        ...

    def delete_secret(
        self,
        *,
        tenant_id: str,
        provider_ref: str,
    ) -> None:
        ...


class SecretStoreService:
    def __init__(
        self,
        *,
        providers: list[SecretStoreProvider],
        default_provider_kind: str,
    ) -> None:
        self._providers = {provider.kind: provider for provider in providers}
        if default_provider_kind not in self._providers:
            raise SecretStoreError(
                f"Unsupported default secret store provider {default_provider_kind!r}."
            )
        self._default_provider_kind = default_provider_kind

    def store_secret(
        self,
        *,
        tenant_id: str,
        secret: dict[str, Any],
        secret_id: str | None = None,
    ) -> str:
        provider = self._providers[self._default_provider_kind]
        provider_ref = provider.store_secret(
            tenant_id=tenant_id,
            secret=secret,
            secret_id=secret_id,
        )
        return f"{provider.kind}:{provider_ref}"

    def get_secret(
        self,
        *,
        tenant_id: str,
        secret_ref: str,
    ) -> dict[str, Any]:
        provider_kind, provider_ref = self._split_secret_ref(secret_ref)
        provider = self._providers.get(provider_kind)
        if provider is None:
            raise SecretStoreError(
                f"Unsupported secret store provider {provider_kind!r}."
            )
        return provider.get_secret(tenant_id=tenant_id, provider_ref=provider_ref)

    def delete_secret(
        self,
        *,
        tenant_id: str,
        secret_ref: str,
    ) -> None:
        provider_kind, provider_ref = self._split_secret_ref(secret_ref)
        provider = self._providers.get(provider_kind)
        if provider is None:
            raise SecretStoreError(
                f"Unsupported secret store provider {provider_kind!r}."
            )
        provider.delete_secret(tenant_id=tenant_id, provider_ref=provider_ref)

    def _split_secret_ref(self, secret_ref: str) -> tuple[str, str]:
        provider_kind, separator, provider_ref = secret_ref.partition(":")
        if not separator or not provider_kind or not provider_ref:
            raise SecretStoreError("Secret ref is malformed.")
        return provider_kind, provider_ref


class S3SecretStoreProvider:
    kind = "s3"

    def __init__(self, settings: Settings) -> None:
        client_config = Config(
            s3={
                "addressing_style": (
                    "path"
                    if self._resolve_force_path_style(settings)
                    else "auto"
                )
            }
        )
        client_kwargs: dict[str, Any] = {
            "region_name": settings.secret_store_s3_region or settings.s3_region,
            "aws_access_key_id": (
                settings.secret_store_s3_access_key_id or settings.s3_access_key_id
            ),
            "aws_secret_access_key": (
                settings.secret_store_s3_secret_access_key or settings.s3_secret_access_key
            ),
            "config": client_config,
        }
        endpoint_url = settings.secret_store_s3_endpoint
        if endpoint_url is None:
            endpoint_url = settings.s3_endpoint
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url

        self._bucket = settings.secret_store_s3_bucket or settings.s3_bucket
        self._prefix = settings.secret_store_s3_prefix.strip("/")
        self._client = boto3.client("s3", **client_kwargs)

    def store_secret(
        self,
        *,
        tenant_id: str,
        secret: dict[str, Any],
        secret_id: str | None = None,
    ) -> str:
        object_key = self._object_key(
            tenant_id=tenant_id,
            secret_id=secret_id or f"sec_{uuid4().hex[:12]}",
        )
        self._client.put_object(
            Bucket=self._bucket,
            Key=object_key,
            Body=json.dumps(secret, indent=2, sort_keys=True).encode("utf-8"),
            ContentType="application/json",
        )
        return object_key

    def get_secret(
        self,
        *,
        tenant_id: str,
        provider_ref: str,
    ) -> dict[str, Any]:
        self._ensure_tenant_scope(tenant_id=tenant_id, provider_ref=provider_ref)
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=provider_ref)
        except ClientError as error:
            error_code = error.response.get("Error", {}).get("Code")
            if error_code in {"NoSuchKey", "404"}:
                raise SecretNotFoundError(provider_ref) from error
            raise SecretStoreError("Failed to load secret from S3.") from error

        payload = json.loads(response["Body"].read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise SecretStoreError("Stored secret payload is not a JSON object.")
        return payload

    def delete_secret(
        self,
        *,
        tenant_id: str,
        provider_ref: str,
    ) -> None:
        self._ensure_tenant_scope(tenant_id=tenant_id, provider_ref=provider_ref)
        self._client.delete_object(Bucket=self._bucket, Key=provider_ref)

    def _object_key(self, *, tenant_id: str, secret_id: str) -> str:
        return f"{self._tenant_prefix(tenant_id)}/{secret_id}.json"

    def _ensure_tenant_scope(self, *, tenant_id: str, provider_ref: str) -> None:
        expected_prefix = f"{self._tenant_prefix(tenant_id)}/"
        if not provider_ref.startswith(expected_prefix):
            raise SecretStoreError("Secret ref does not belong to the requested tenant.")

    def _resolve_force_path_style(self, settings: Settings) -> bool:
        if settings.secret_store_s3_force_path_style is not None:
            return settings.secret_store_s3_force_path_style
        return settings.s3_force_path_style

    def _tenant_prefix(self, tenant_id: str) -> str:
        base_key = f"tenants/{tenant_id}/secrets"
        if not self._prefix:
            return base_key
        return f"{self._prefix}/{base_key}"


def build_secret_store(settings: Settings) -> SecretStoreService:
    provider_kind = settings.secret_store_provider.strip().lower()
    if provider_kind != "s3":
        raise SecretStoreError(
            f"Unsupported secret store provider {settings.secret_store_provider!r}."
        )
    return SecretStoreService(
        providers=[S3SecretStoreProvider(settings)],
        default_provider_kind=provider_kind,
    )
