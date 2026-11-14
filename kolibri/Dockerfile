# Kolibri (offline lessons: Khan Academy and more) for Pi-NOMAD.
#
# Learning Equality publishes no current Docker image (the ones on Docker Hub are years old),
# but Kolibri is an ordinary Python package and the Raspberry Pi 5 is one of their tested
# devices. So this image is just Python plus that package, built on the Pi itself for arm64.
# The version is pinned: check the release notes before raising it.
FROM python:3.12-slim

# iproute2: Kolibri lists the network addresses it can be reached on with the "ip" command.
RUN apt-get update \
 && apt-get install -y --no-install-recommends iproute2 \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir kolibri==0.19.5

# Everything Kolibri keeps (accounts, progress, downloaded lessons) lives in KOLIBRI_HOME,
# which compose maps to /srv/nomad/kolibri. Interactive lessons are served from a second port,
# and the browser is told that port's number, so both must be published unchanged.
ENV KOLIBRI_HOME=/kolibri \
    KOLIBRI_HTTP_PORT=8085 \
    KOLIBRI_ZIP_CONTENT_PORT=8086
EXPOSE 8085 8086
CMD ["kolibri", "start", "--foreground"]
