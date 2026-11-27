FROM python:3.12-slim-bookworm

ARG BCC_AGENT_COMMIT
WORKDIR /opt/bcc-review
COPY pyproject.toml ./
COPY src/ ./src/
RUN test -n "$BCC_AGENT_COMMIT" && python -m pip install --no-cache-dir ".[all]"

ENV BCC_AGENT_COMMIT=$BCC_AGENT_COMMIT \
    PYTHONUNBUFFERED=1
WORKDIR /data
ENTRYPOINT ["python", "-m", "bcc_review"]
