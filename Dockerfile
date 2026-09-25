FROM ghcr.io/astral-sh/uv:0.12.15@sha256:62f8c047d0a0e9ece6b53fc63df902585a67a47a7f318ddec4a37db586edc8e3 AS uv
FROM node:24.21.0-bookworm-slim@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6 AS cards
WORKDIR /build
RUN npm install --global pnpm@12.4.2
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.json ./
COPY apps/mcp-app/ ./apps/mcp-app/
COPY apps/web/package.json ./apps/web/package.json
COPY hirz/adapters/doorbell/twin/snapshot.svg ./hirz/adapters/doorbell/twin/snapshot.svg
RUN pnpm install --frozen-lockfile && pnpm --filter mcp-app build

FROM rust:1.98.1-slim-bookworm@sha256:ebd900bae66fd508b466cef82d64a83a5fb34682e4c8b2797a42908bddc95a57 AS dogwood
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN git init --quiet && git fetch --depth=1 https://github.com/dogwood-policy/dogwood.git 996d756de1013b7ae209a14f566a80375a59f2f0 \
    && git checkout --detach FETCH_HEAD
COPY scripts/dogwood.Cargo.lock Cargo.lock
RUN cargo build --locked --release -p dogwood-cli
RUN cp target/release/dogwood /build/dogwood-reference
COPY scripts/dogwood-clone.patch /build/dogwood-clone.patch
RUN git apply dogwood-clone.patch
COPY scripts/dogwood-helper.rs /build/dogwood-cli/src/bin/dogwood-helper.rs
RUN cargo build --locked --release --bin dogwood-helper

FROM python:3.12.13-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36

COPY --from=uv /uv /usr/local/bin/uv
COPY --from=dogwood /build/dogwood-reference /usr/local/bin/dogwood
COPY --from=dogwood /build/target/release/dogwood-helper /usr/local/bin/dogwood-helper
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock README.md LICENSE build_backend.py ./
COPY hirz/ ./hirz/
COPY --from=cards /build/hirz/mcp/ui/ ./hirz/mcp/ui/
RUN uv sync --locked --no-dev --no-editable --no-cache \
    && useradd --uid 10001 --no-create-home hirz
USER hirz
EXPOSE 8000
CMD ["uvicorn", "hirz.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
