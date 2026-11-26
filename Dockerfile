# Агент bcc-review в контейнере: тот же Python и те же версии, что в requirements.txt.
#
#   docker build -t bcc-review .
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

# Коммит агента для паспорта отчёта: аргумент сборки BCC_AGENT_COMMIT, иначе — из .git/HEAD контекста сборки
# (в образ копируются только HEAD и ссылки, см. .dockerignore). Без .git (архив ZIP) — «unknown».
COPY scripts/git_commit.py /tmp/git_commit.py
COPY pyproject.toml .gi[t] /tmp/gitmeta/
ARG BCC_AGENT_COMMIT=""
RUN commit="${BCC_AGENT_COMMIT:-$(python /tmp/git_commit.py /tmp/gitmeta)}" \
    && echo "${commit:-unknown}" > /app/AGENT_COMMIT && echo "коммит агента: ${commit:-unknown}" \
    && rm -rf /tmp/gitmeta /tmp/git_commit.py

# Запуск от root намеренно: смонтированный ./reports должен быть доступен на запись при любом uid хоста.
RUN mkdir -p /app/reports /app/runs /app/.bcc_cache

ENTRYPOINT ["sh", "-c", "BCC_AGENT_COMMIT=\"${BCC_AGENT_COMMIT:-$(cat /app/AGENT_COMMIT)}\" exec python -m bcc_review \"$@\"", "bcc-review"]
CMD ["--help"]
