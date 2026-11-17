FROM docker.io/library/python:3.14.8-alpine3.24@sha256:f6a589d43c42b9e7f7dc67a12d37132491f362859a5d750607710cc56da3bc72 AS builder
COPY docker/homeassistant/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir setuptools==84.2.1 \
    && pip install --no-cache-dir --prefix /install -r /tmp/requirements.txt
WORKDIR /usr/src/pysignalduino
COPY pyproject.toml README.adoc LICENSE ./
COPY signalduino ./signalduino
COPY sd_protocols ./sd_protocols
RUN pip install --no-cache-dir --no-deps --no-build-isolation --prefix /install .

FROM docker.io/library/python:3.14.8-alpine3.24@sha256:f6a589d43c42b9e7f7dc67a12d37132491f362859a5d750607710cc56da3bc72
LABEL org.opencontainers.image.source="https://github.com/RFD-FHEM/PySignalduino" \
      org.opencontainers.image.description="USB MQTT actuator gateway with Home Assistant discovery" \
      org.opencontainers.image.licenses="GPL-3.0-only"
COPY --from=builder /install/ /usr/local/
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 1000:1000
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=3 CMD ["python", "-m", "signalduino.homeassistant.health"]
CMD ["python", "-m", "signalduino.homeassistant"]
