# Full TeX Live plus a tiny Python service that serves individual TeX files
# (and generates fonts on demand) to the in-browser compiler. See proxy.py.
#
# The base image is a rolling full TeX Live. The in-browser engine is TeX Live
# 2023; class/style/font *sources* are effectively version-agnostic, so a newer
# tree resolves them fine. Pin by digest here if you need strict reproducibility.
ARG TEXLIVE_IMAGE=texlive/texlive:latest-full
FROM ${TEXLIVE_IMAGE}

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*

COPY proxy.py /usr/local/bin/proxy.py

EXPOSE 8771
CMD ["python3", "/usr/local/bin/proxy.py"]
