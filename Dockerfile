FROM koalaman/shellcheck:v0.11.0 AS src
FROM python:3.15-slim AS base

WORKDIR /app

COPY --from=src /bin/shellcheck /bin/

# prevent 9Mb of cached bytecode files (.pyc)
ENV PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt requirements.txt
RUN pip3 install --no-compile --no-cache-dir -r requirements.txt

COPY yaml_shellcheck.py .

USER 1000
ENTRYPOINT [ "python3", "yaml_shellcheck.py"]

LABEL org.opencontainers.image.source="https://github.com/mschuett/yaml-shellcheck"
LABEL org.opencontainers.image.title="YAML-Shellcheck" \
      org.opencontainers.image.description="run shellcheck on YAML CI-config files" \
      org.opencontainers.image.url="https://github.com/mschuett/yaml-shellcheck" \
      org.opencontainers.image.licenses="BSD-2-Clause" \
      org.opencontainers.image.base.name="docker.io/python:3.15-slim"
