FROM ubuntu:24.04

WORKDIR /var/local

RUN apt-get update && apt-get install -y \
    perl wget libfontconfig1 xz-utils ca-certificates && \
    wget -qO- "https://yihui.org/tinytex/install-bin-unix.sh" | sh && \
    apt-get clean

ENV PATH="${PATH}:/root/bin"

# Project-installed packages land here rather than on top of the
# distribution, so mounting a cache doesn't shadow TinyTeX itself.
ENV TEXMFHOME=/root/texmf

RUN fmtutil-sys --all

# A curated core rather than whole collections: the tools, plus the
# packages a real journal paper turned out to need. Determined by
# compiling an AASTeX 6.3.1 paper against the minimal image and
# installing whatever it asked for, one at a time.
# revtex4-1 has to be here rather than fetched on demand: aastex631.cls
# refuses to load without it and stops without reporting a missing file,
# so nothing can auto-install it.
# latexdiff is here because `calkit latex diff` needs it; perl above is
# what makes that possible.
RUN tlmgr option repository "https://mirror.ctan.org/systems/texlive/tlnet" && \
    i=1; \
    until [ "$i" -gt 3 ]; do \
        tlmgr update --self && \
        tlmgr install biber \
            latexmk \
            latexdiff \
            latexindent \
            chktex \
            texliveonfly \
            synctex \
            texcount \
            revtex4-1 \
            textcase \
            epsf \
            ulem \
            threeparttable \
            multirow \
            units \
            grfext \
            subfigure \
            enumitem \
            todonotes \
            lineno && break; \
        echo "tlmgr failed on attempt ${i}/3, retrying in 15s..." >&2; \
        i=$((i + 1)); \
        sleep 15; \
    done && \
    [ "$i" -le 3 ] && \
    tlmgr path add

# The user tree is initialized at run time, not here: a mounted cache
# starts empty and would hide anything this layer created.
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
