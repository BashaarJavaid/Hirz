"""Select an explicit AWS role, retaining the existing local image default."""

import os

import uvicorn


def main() -> None:
    role = os.environ.get("HIRZ_AWS_ROLE")
    if role is None:
        uvicorn.run("hirz.api.app:app", host="0.0.0.0", port=8000)
    elif role in {"worker", "mcp"}:
        uvicorn.run(
            "hirz.aws.app:"
            + ("create_worker" if role == "worker" else "create_runtime"),
            factory=True,
            host="0.0.0.0",
            port=8000,
            access_log=False,
        )
    else:
        raise ValueError("Unknown AWS process role")


if __name__ == "__main__":
    main()
