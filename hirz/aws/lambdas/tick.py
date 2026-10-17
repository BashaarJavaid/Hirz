"""Both EventBridge delivery paths carry no household or action authority."""

import os
import re
import urllib.request
from typing import Any

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]


def handler(event: dict[str, Any], context: Any) -> None:
    secret = boto3.client(
        "secretsmanager",
        config=Config(connect_timeout=2, read_timeout=3, retries={"max_attempts": 1}),
    ).get_secret_value(SecretId=os.environ["HIRZ_TICK_SECRET"])["SecretString"]
    if not re.fullmatch(r"[0-9a-f]{64}", secret):
        raise ValueError("Tick secret has not been initialized")
    url = os.environ["HIRZ_TICK_URL"]
    if not re.fullmatch(r"https://[a-z0-9]+\.cloudfront\.net/internal/tick", url):
        raise ValueError("Tick requires the exact CloudFront HTTPS endpoint")
    request = urllib.request.Request(
        url, method="POST", headers={"Authorization": "Bearer " + secret}
    )

    # No redirect may forward the bearer to a different endpoint.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args: Any, **kwargs: Any) -> None:
            return None

    with urllib.request.build_opener(NoRedirect).open(request, timeout=65) as response:
        if response.status != 204:
            raise RuntimeError("Worker did not complete its tick")
