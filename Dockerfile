# MediaHub: one login in front of Radarr, Sonarr, Lidarr, Bookarr, qBittorrent and SABnzbd.
# Pure Python standard library, so the image is just Python plus two folders.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="MediaHub" \
      org.opencontainers.image.description="One web page and one login for Radarr, Sonarr, Lidarr, Bookarr, qBittorrent and SABnzbd" \
      org.opencontainers.image.licenses="NOASSERTION"

ENV HUB_PORT=8690 \
    HUB_CONFIG=/config \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY server.py ./
COPY static ./static

# Your login, app addresses, API keys and the image cache live here. Map it to a folder on the host.
VOLUME /config
EXPOSE 8690

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/auth/me' % os.environ.get('HUB_PORT','8690'), timeout=4)" || exit 1

CMD ["python", "/app/server.py"]
