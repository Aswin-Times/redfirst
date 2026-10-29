# Sandbox image for running generated pytest tests. No network is used at run time.
# Build: docker build -t redfirst-sandbox-python:3.12 sandbox-images/python
FROM python:3.12-slim

ENV PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN pip install pytest==8.3.4 && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin runner
USER 10001:10001
WORKDIR /repo
