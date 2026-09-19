#!/bin/sh
# A mounted package cache starts out empty, which hides whatever the image
# put at TEXMFHOME, so the user tree has to be initialized here rather than
# at build time. Without it, `tlmgr --usermode install` fails with
# "Cannot determine type of tlpdb".
if [ -n "$TEXMFHOME" ] && [ ! -d "$TEXMFHOME/tlpkg" ]; then
    tlmgr init-usertree > /dev/null 2>&1 || true
fi
exec "$@"
