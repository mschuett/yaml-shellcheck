FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y shellcheck \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.txt
RUN pip3 install -r requirements.txt

COPY . .

ENTRYPOINT [ "python3", "yaml_shellcheck.py"]
