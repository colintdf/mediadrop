FROM python:3.12-slim-bookworm

ARG PUID=501
ARG PGID=20

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MEDIADROP_DATA=/data \
    MEDIADROP_CONTAINER=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && if ! getent group "${PGID}" >/dev/null; then groupadd --gid "${PGID}" mediadrop; fi \
    && useradd --uid "${PUID}" --gid "${PGID}" --no-create-home --home-dir /app mediadrop \
    && mkdir -p /app /data /music \
    && chown "${PUID}:${PGID}" /app /data /music

WORKDIR /app
COPY --chown=${PUID}:${PGID} server.py artwork.py ./
COPY --chown=${PUID}:${PGID} web ./web

USER ${PUID}:${PGID}
EXPOSE 12345
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:12345/api/health', timeout=3).read()"
CMD ["python3", "server.py", "--host", "0.0.0.0", "--port", "12345"]
