# Агент bcc-review в контейнере: тот же Python и те же версии, что в requirements.txt.
#
#   docker build -t bcc-review --build-arg BCC_AGENT_COMMIT=$(git rev-parse HEAD) .
#   docker run --rm --env-file .env -v "$(pwd)/reports:/app/reports" bcc-review \
#       release/input/requirements.md reports/docker/requirements.md
#
# Свой документ положите в ./reports и передайте путь reports/<файл>.
# Провайдер claude_cli в контейнере недоступен (нет авторизованного `claude`): используйте gemini, anthropic,
# openai (Ollama на хосте: OPENAI_BASE_URL=http://host.docker.internal:11434/v1) или offline.

FROM python:3.12-slim

ENV PYTHONUTF8=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install -r requirements.txt

COPY pyproject.toml ./
COPY src ./src
COPY contracts ./contracts
COPY release/input ./release/input
COPY examples ./examples

# pymupdf без подсказки про pymupdf_layout в выводе
ENV PYMUPDF_SUGGEST_LAYOUT_ANALYZER=0
RUN python -m pip install --no-deps -e .

# В образе нет каталога .git: коммит сборки для паспорта отчёта передаётся при сборке.
ARG BCC_AGENT_COMMIT=""
ENV BCC_AGENT_COMMIT=${BCC_AGENT_COMMIT}

# Запуск от root намеренно: смонтированный ./reports должен быть доступен на запись при любом uid хоста.
RUN mkdir -p /app/reports /app/runs /app/.bcc_cache

ENTRYPOINT ["python", "-m", "bcc_review"]
CMD ["--help"]
