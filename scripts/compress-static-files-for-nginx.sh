#!/bin/sh

set -eu

if [ ! -d '/opt/tulila' ] ; then
  echo 'Tulila must be installed first.' >&2
  exit 1
fi

if [ "$(id -u)" -ne 0 ] ; then
  echo 'This script must be run as root.' >&2
  exit 1
fi

find '/opt/tulila/modules/tulila_server/rsrc/assets' \
 \( -type f -name '*.css' -o -name '*.js' \) \
 -exec sh -c '[ -f "$0.gz" ] || gzip -k9 "$0"' {} \;

# Only use brotli compression if it is available
# By default, nginx only supports gzip
if [ -x "$(command -v brotli)" ] ; then
  find '/opt/tulila/modules/tulila_server/rsrc/assets' \
   \( -type f -name '*.css' -o -name '*.js' \) \
   -exec sh -c '[ -f "$0.br" ] || brotli --best "$0"' {} \;
fi

echo 'Static files compressed for nginx.'
