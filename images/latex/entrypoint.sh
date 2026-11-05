#!/bin/sh
# In a Calkit project, packages fetched at run time are kept with the
# project, in its gitignored .calkit/local, which the working directory
# mount already covers. That makes any Docker environment built on this
# image able to fetch what a document needs, with nothing extra mounted.
# Only when TEXMFHOME is still the image's own, so a caller that set it
# gets what it asked for.
if [ "$TEXMFHOME" = /texmf ] && [ -d .calkit/local ]; then
    TEXMFHOME="$PWD/.calkit/local/texmf"
    export TEXMFHOME
    mkdir -p "$TEXMFHOME" 2>/dev/null || true
fi
# A mounted package cache starts out empty, which hides whatever the image
# put at TEXMFHOME, so the user tree has to be initialized here rather than
# at build time. Without it, `tlmgr --usermode install` fails with
# "Cannot determine type of tlpdb".
if [ -n "$TEXMFHOME" ] && [ -w "$TEXMFHOME" ] &&
    [ ! -d "$TEXMFHOME/tlpkg" ]; then
    tlmgr init-usertree > /dev/null 2>&1 || true
fi
exec "$@"
