FROM ghcr.io/0xmassi/webclaw:latest

RUN apt-get update && apt-get install -y --no-install-recommends wget \
    && rm -rf /var/lib/apt/lists/*

CMD ["webclaw-server"]
