# Headless LibreOffice at one exact release, so a document converts the same
# way on every machine
FROM debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad

ARG LIBREOFFICE_VERSION=26.8.1.1
# The Document Foundation signs its archives but publishes no checksums, so
# these are the archives' own, taken when the version was pinned
ARG LIBREOFFICE_SHA256_AMD64=30903df3b9f61360d9660cd707de48cd2831469114492a5008ed58a0ac77d044
ARG LIBREOFFICE_SHA256_ARM64=1b069c20dd237f6decad3ea02cb02f39fdf458b03d09c2a9facb7b9b71e6a27a
ARG TARGETARCH

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates curl fontconfig fonts-dejavu-core fonts-liberation \
        libcairo2 libcups2 libdbus-1-3 libglib2.0-0t64 libnss3 libsm6 \
        libx11-xcb1 libxinerama1; \
    case "$TARGETARCH" in \
        amd64) arch=x86-64; dir=x86_64; sha="$LIBREOFFICE_SHA256_AMD64" ;; \
        arm64) arch=aarch64; dir=aarch64; sha="$LIBREOFFICE_SHA256_ARM64" ;; \
        *) echo "No LibreOffice build for $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    curl -fsSLo /tmp/lo.tar.gz \
        "https://downloadarchive.documentfoundation.org/libreoffice/old/${LIBREOFFICE_VERSION}/deb/${dir}/LibreOffice_${LIBREOFFICE_VERSION}_Linux_${arch}_deb.tar.gz"; \
    echo "$sha  /tmp/lo.tar.gz" | sha256sum -c -; \
    mkdir /tmp/lo; \
    tar xzf /tmp/lo.tar.gz -C /tmp/lo --strip-components=2; \
    # Only what converting text documents needs: Writer, and Math for
    # equations, without Calc, Impress, Draw, or Base
    cd /tmp/lo; \
    dpkg -i "libreoffice${LIBREOFFICE_VERSION%.*.*}"_*.deb \
        *-ure_*.deb *-core_*.deb \
        *-images_*.deb *-ooofonts_*.deb *-graphicfilter_*.deb \
        *-en-us_*.deb *-writer_*.deb *-math_*.deb; \
    cd /; \
    ln -s "$(ls -d /opt/libreoffice*)/program/soffice" /usr/local/bin/soffice; \
    apt-get purge -y --auto-remove curl; \
    rm -rf /tmp/lo /tmp/lo.tar.gz /var/lib/apt/lists/*

# Anyone the container runs as needs somewhere to keep a profile
ENV HOME=/tmp
WORKDIR /work
CMD ["soffice", "--version"]
