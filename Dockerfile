FROM python:3.13-slim

WORKDIR /app

COPY --from=koalaman/shellcheck:v0.11.0 /bin/shellcheck /bin/

# prevent 9Mb of cached bytecode files (.pyc)
ENV PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt requirements.txt
RUN pip3 install --no-compile --no-cache-dir -r requirements.txt

COPY yaml_shellcheck.py .

USER 1000
ENTRYPOINT [ "python3", "yaml_shellcheck.py"]
