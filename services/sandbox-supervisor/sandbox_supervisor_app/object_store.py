from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config

from .config import Settings


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

    def download_file(self, object_key: str, local_path: Path) -> None:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(
            Bucket=self.bucket,
            Key=object_key,
            Filename=str(local_path),
        )

    def download_json(self, object_key: str) -> dict[str, Any]:
        response = self.client.get_object(Bucket=self.bucket, Key=object_key)
        payload = response["Body"].read()
        return json.loads(payload.decode("utf-8"))
