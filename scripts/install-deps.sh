#!/bin/sh

set -eu

# This script will install all of the dependencies required by Tulila.
# It is written for, _and will only run on_, an Ubuntu 24.04 system.
# It will absolutely not work on any other distribution (including an
# older or newer version of Ubuntu), so before we take any actions
# we make sure the system is supported.
# Unfortunately, it's not really possible to install all these
# dependencies in a platform-agnostic way (a separate script would
# need to be written for Red Hat, Arch, etc.).

if [ ! -x "$(command -v lsb_release)" ] ; then
  echo 'Unable to execute lsb_release.' >&2
  exit 1
fi

if [ "$(lsb_release -si 2>/dev/null)" != 'Ubuntu' ] || [ "$(lsb_release -sr 2>/dev/null)" != '24.04' ] ; then
  echo 'This script is written for Ubuntu 24.04 only.' >&2
  echo 'For all other distributions, you will have to install dependencies manually.' >&2
  exit 1
fi

if [ "$(id -u)" -ne 0 ] ; then
  echo 'This script must be run as root.' >&2
  exit 1
fi

export PYTHONWARNINGS=ignore  # Cut down on gdebi line-spam

echo "Installing Tulila's dependencies ..."

add-apt-repository -yn ppa:deadsnakes/ppa >/dev/null
apt-get -qq update
apt-get install -y python3.13 python3.13-venv pkexec gdebi-core unzip curl

printf '%s' 'Downloading required files ...'
download_dir=$(mktemp -d)
curl "-sLo$download_dir/pledge" https://justine.lol/pledge/pledge-1.8.com
curl "-sLo$download_dir/graphviz-debs.tar.xz" https://gitlab.com/api/v4/projects/4207231/packages/generic/graphviz-releases/12.2.1/ubuntu_24.04_graphviz-12.2.1-debs.tar.xz
curl "-sLo$download_dir/lm2.004otf.zip" https://www.gust.org.pl/projects/e-foundry/latin-modern/download/lm2.004otf.zip
tar -xf "$download_dir/graphviz-debs.tar.xz" -C "$download_dir" 'graphviz_12.2.1-1_amd64.deb'
tar -xf "$download_dir/graphviz-debs.tar.xz" -C "$download_dir" 'libgraphviz4_12.2.1-1_amd64.deb'
unzip -q -j "$download_dir/lm2.004otf.zip" 'lmsans12-regular.otf' -d "$download_dir"
unzip -q -j "$download_dir/lm2.004otf.zip" 'lmsans12-oblique.otf' -d "$download_dir"
echo ' complete.'

cp "$download_dir/pledge" /usr/local/bin
chmod +x /usr/local/bin/pledge

gdebi -n "$download_dir/libgraphviz4_12.2.1-1_amd64.deb"
gdebi -n "$download_dir/graphviz_12.2.1-1_amd64.deb"

cp "$download_dir/lmsans12-regular.otf" /usr/local/share/fonts
cp "$download_dir/lmsans12-oblique.otf" /usr/local/share/fonts
fc-cache -fs

rm -rf "$download_dir"

echo
echo 'Dependencies installed.'
