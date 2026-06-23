# Reproducible quant backend pinned to Python 3.12.
# Host Python is 3.14 (bleeding edge); several quant wheels (py_vollib, scipy, etc.)
# may not yet ship cp314 wheels, so all backend dev/test/CI runs in this container.
# See docs/decisions/0005-python-3.12-docker-pin.md
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/backend/src

WORKDIR /app/backend

# Install dependencies first (better layer caching). Copy only the metadata, then the source.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --upgrade pip && pip install ".[dev]"

# Bring in the rest of the backend (tests, scripts). The whole repo is also bind-mounted
# at /app by docker-compose at runtime, which overlays live source + data/fixtures.
COPY . .

# Run as non-root.
RUN useradd --create-home --uid 1000 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# Default: serve the API + static page. docker-compose overrides command for tests/demo.
CMD ["uvicorn", "oip.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
