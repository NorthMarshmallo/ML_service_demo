FROM python:3.11.18-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-dev --no-install-project

COPY src/ src/
RUN uv sync --frozen --no-dev

COPY artifact/ artifact/

COPY .dvc/config .dvc/config
COPY datasets/*.dvc datasets/
RUN uv run --no-sync dvc config --local core.no_scm true

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "amr_prediction.service.app:app", "--host", "0.0.0.0", "--port", "8000"]