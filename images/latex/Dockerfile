FROM ubuntu:24.04

WORKDIR /var/local

# TinyTeX goes in /opt rather than /root, and readable by everyone:
# Calkit runs containers as the invoking user so output isn't owned by
# root, and /root is 0700, which would leave that user with no TeX at all.
ENV TINYTEX_DIR=/opt

RUN apt-get update && apt-get install -y \
    perl wget libfontconfig1 xz-utils ca-certificates && \
    wget -qO- "https://yihui.org/tinytex/install-bin-unix.sh" | sh && \
    apt-get clean && \
    chmod -R a+rX /opt/.TinyTeX

# Both architectures, since the image is built for each and the
# directory is named after the one it was built on
ENV PATH="${PATH}:/opt/.TinyTeX/bin/aarch64-linux"
ENV PATH="${PATH}:/opt/.TinyTeX/bin/x86_64-linux"

# Project-installed packages land here rather than on top of the
# distribution, so mounting a cache doesn't shadow TinyTeX itself. It has
# to be writable by whoever runs the container, not just root.
ENV TEXMFHOME=/texmf
RUN mkdir -p /texmf && chmod 1777 /texmf

# Running as the invoking user means there is no passwd entry for them,
# so Docker falls back to HOME=/, which they can't write to. Anything
# that caches under HOME, e.g., fontconfig, fails against that.
ENV HOME=/home/calkit
RUN mkdir -p /home/calkit && chmod 1777 /home/calkit

RUN fmtutil-sys --all

# A curated core rather than whole collections: the tools, the classes
# for journals people actually submit to, and what those classes need.
# Determined by compiling a paper in each class against the minimal
# image and installing whatever it asked for, one at a time.
# Two of these can't be fetched on demand, which is why fetching on
# demand isn't enough on its own. aastex631.cls refuses to load without
# revtex4-1 and stops without reporting a missing file. newtx needs
# txfonts' metrics, which surface as "Metric (TFM) file not found"
# rather than as a missing .sty. Nothing can auto-install either.
# sectsty and cite are what Calkit's own paper templates ask for, which
# is what someone starting a project gets before they have asked for
# anything.
# latexdiff is here because `calkit latex diff` needs it; perl above is
# what makes that possible.
# cm-super supplies Type 1 versions of the EC fonts that elsarticle and
# mnras ask for. Without it TeX generates bitmaps at run time, which
# needs a writable texmf-var and produces worse PDFs; texmf-var is made
# writable below anyway, for whatever else wants to generate a font.
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
            lineno \
            caption \
            newtx \
            txfonts \
            xpatch \
            xstring \
            carlisle \
            fontaxes \
            oberdiek \
            elsarticle \
            revtex \
            ieeetran \
            acmart \
            mnras \
            llncs \
            aliascnt \
            achemso \
            setspace \
            microtype \
            totpages \
            everyshi \
            environ \
            hyperxmp \
            ncctools \
            cmap \
            comment \
            fancyhdr \
            preprint \
            cm-super \
            sectsty \
            cite && break; \
        echo "tlmgr failed on attempt ${i}/3, retrying in 15s..." >&2; \
        i=$((i + 1)); \
        sleep 15; \
    done && \
    [ "$i" -le 3 ] && \
    tlmgr path add && \
    chmod -R a+rX /opt/.TinyTeX && \
    chmod -R a+rwX /opt/.TinyTeX/texmf-var

# The user tree is initialized at run time, not here: a mounted cache
# starts empty and would hide anything this layer created.
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
