"""Bounded CLI credential bridge; stdout is for the SDK only, never a log."""

import subprocess
import sys
import time


def credentials() -> str:
    deadline = time.monotonic() + 120
    for attempt in range(3):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            result = subprocess.run(
                [
                    "aws",
                    "configure",
                    "export-credentials",
                    "--profile",
                    "hirz-operator-login",
                    "--format",
                    "process",
                    "--cli-connect-timeout",
                    "5",
                    "--cli-read-timeout",
                    "15",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=min(35, remaining),
            )
        except subprocess.TimeoutExpired:
            pass
        else:
            if result.returncode == 0:
                return result.stdout
            if "Your session has expired" in result.stderr:
                raise RuntimeError(
                    "Operator login expired; refresh hirz-operator-login."
                )
            if (
                'Could not connect to the endpoint URL: "https://us-east-1.signin.aws.amazon.com/v1/token"'
                not in result.stderr
            ):
                raise RuntimeError(
                    "Operator credential retrieval failed; inspect the login privately."
                )
        if attempt < 2:
            time.sleep(min(5, max(0, deadline - time.monotonic())))
    raise RuntimeError(
        "Operator credential connection failed within the bounded retry window."
    )


def main() -> int:
    try:
        value = credentials()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    sys.stdout.write(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
