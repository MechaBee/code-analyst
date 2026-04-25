from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .config import Settings


class ObjectStoreKeyNotFound(RuntimeError):
    pass


class ObjectStore:
    def __init__(self, settings: Settings) -> None:
        client_config = Config(
            s3={"addressing_style": "path" if settings.s3_force_path_style else "auto"}
        )
        self.bucket = settings.s3_bucket
        client_kwargs: dict[str, Any] = {
            "region_name": settings.s3_region,
            "aws_access_key_id": settings.s3_access_key_id,
            "aws_secret_access_key": settings.s3_secret_access_key,
            "config": client_config,
        }
        if settings.s3_endpoint:
            client_kwargs["endpoint_url"] = settings.s3_endpoint
        self.client = boto3.client(
            "s3",
            **client_kwargs,
        )

    def upload_bytes(
        self,
        object_key: str,
        payload: bytes,
        content_type: str,
    ) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=object_key,
            Body=payload,
            ContentType=content_type,
        )

    def upload_json(self, object_key: str, payload: Any) -> None:
        encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.upload_bytes(
            object_key=object_key,
            payload=encoded,
            content_type="application/json",
        )

    def upload_file(
        self,
        object_key: str,
        local_path: Path,
        content_type: str,
    ) -> None:
        extra_args = {"ContentType": content_type}
        self.client.upload_file(
            Filename=str(local_path),
            Bucket=self.bucket,
            Key=object_key,
            ExtraArgs=extra_args,
        )

    def download_bytes(self, object_key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=object_key)
        except ClientError as error:
            error_code = error.response.get("Error", {}).get("Code")
            if error_code in {"NoSuchKey", "404"}:
                raise ObjectStoreKeyNotFound(object_key) from error
            raise
        return response["Body"].read()

    def download_json(self, object_key: str) -> Any:
        payload = self.download_bytes(object_key)
        return json.loads(payload.decode("utf-8"))

    def list_keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        continuation_token: str | None = None
        while True:
            request_kwargs: dict[str, Any] = {
                "Bucket": self.bucket,
                "Prefix": prefix,
            }
            if continuation_token:
                request_kwargs["ContinuationToken"] = continuation_token
            response = self.client.list_objects_v2(**request_kwargs)
            for item in response.get("Contents", []):
                keys.append(item["Key"])
            if not response.get("IsTruncated"):
                break
            continuation_token = response.get("NextContinuationToken")
        return keys
