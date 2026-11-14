ARG TERMUX_BASE_IMAGE=ghcr.io/termux/package-builder:latest
FROM ${TERMUX_BASE_IMAGE}
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends autopoint \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
USER builder:builder
WORKDIR /home/builder/termux-packages
