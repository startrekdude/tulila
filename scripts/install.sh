#!/bin/sh

set -eu

if [ -d '/opt/tulila' ] ; then
  echo 'Tulila is already installed.' >&2
  exit 1
fi

if [ ! -x "$(command -v python3.13)" ] ; then
  echo 'Tulila requires Python 3.13 ("python3.13"), but it is not installed.' >&2
  exit 1
fi

# Debian and derivatives ship Python 3 virtual environment support in a separate package.
# This checks that it is installed (without using Debian-specific commands, as this
# install script should not be tied to a single platform).
if [ ! -d '/usr/lib/python3.13/ensurepip' ] && [ ! -d '/usr/lib64/python3.13/ensurepip' ] ; then
  echo 'Tulila requires virtual environment support for Python 3.13 ("python3.13-venv"), but it is not installed.' >&2
  exit 1
fi

if [ ! -x "$(command -v pledge)" ] ; then
  echo 'Tulila requires pledge, but it is not installed.' >&2
  exit 1
fi

if [ ! -x "$(command -v pkexec)" ] ; then
  echo 'Tulila requires pkexec, but it is not installed.' >&2
  exit 1
fi

if [ ! -x "$(command -v dot)" ] ; then
  echo 'Tulila requires Graphviz, but it is not installed.' >&2
  exit 1
fi

if ! dot -Tsvg_inline </dev/null >/dev/null 2>&1 ; then
  echo 'Tulila requires a version of Graphviz with support for -Tsvg_inline, which the installed version lacks.' >&2
  exit 1
fi

if [ -z "${SKIP_FONT_CHECK+1}" ] && ! fc-list | grep -q 'Latin Modern Sans' ; then
  echo 'Tulila works best if Latin Modern Sans is installed.' >&2
  echo 'To skip this check, define SKIP_FONT_CHECK.' >&2
  exit 1
fi

if [ "$(id -u)" -ne 0 ] ; then
  echo 'This install script must be run as root.' >&2
  exit 1
fi

echo 'Installing Tulila ...'

if [ ! -d '/var/opt' ] ; then
  mkdir /var/opt
  echo '/var/opt did not exist and was created.'
fi

mkdir -p /opt/tulila

# Where to copy files from, a.k.a. one directory above where the install script is located
tulila_root=$(dirname "$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)")

cp -r "$tulila_root/modules" /opt/tulila
cp -r "$tulila_root/bin" /opt/tulila
cp -r "$tulila_root/challenges" /opt/tulila

python3.13 -m venv /opt/tulila/venv
/opt/tulila/venv/bin/python3 -m pip install --no-cache-dir --disable-pip-version-check -q -r "$tulila_root/requirements.lock"
find /opt/tulila -type d -name '__pycache__' -prune -exec rm -rf {} \; || true  # Removing these caches is best-effort

adduser --quiet --system --group --home /var/opt/tulila tulila
groupadd --system 'tulila-admins'

cat >/usr/lib/systemd/system/tulila.service <<'EOF'
[Unit]
Description=Tulila Server
BindsTo=tulila.socket
After=tulila.socket

[Service]
Type=simple
User=tulila
Group=tulila
ExecStart=/opt/tulila/bin/tulila-server
UMask=0027

CapabilityBoundingSet=
LockPersonality=yes
NoNewPrivileges=yes
RemoveIPC=yes
PrivateDevices=yes
PrivateUsers=yes
PrivateTmp=yes
PrivateMounts=yes
ProtectProc=invisible
ProtectClock=yes
ProtectControlGroups=yes
ProtectHome=yes
ProtectKernelLogs=yes
ProtectKernelModules=yes
ProtectKernelTunables=yes
ProtectHostname=yes
ProtectSystem=strict
ReadWritePaths=/var/opt/tulila
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
RestrictNamespaces=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
SystemCallArchitectures=native
SystemCallErrorNumber=EPERM
SystemCallFilter=~@clock @debug @module @mount @raw-io @reboot @setuid @swap @privileged @cpu-emulation @obsolete

[Install]
WantedBy=multi-user.target
EOF

cat >/usr/lib/systemd/system/tulila.socket <<'EOF'
[Unit]
Description=Tulila Server Socket
BindsTo=tulila.service

[Install]
WantedBy=sockets.target
EOF

mkdir -p /etc/systemd/system/tulila.service.d
cat >/etc/systemd/system/tulila.service.d/override.conf <<'EOF'
[Service]
Environment="TULILA_SERVER_CHALLENGE_PATH=/opt/tulila/challenges"
EOF

mkdir -p /etc/systemd/system/tulila.socket.d
cat >/etc/systemd/system/tulila.socket.d/override.conf <<'EOF'
[Socket]
ListenStream=127.0.0.1:10617
EOF

# Using Polkit, grant privileges to (members of) tulila-admins.
# They may:
#   1. Run the Tulila management scripts as "tulila" using pkexec.
#      This is required to access and modify Tulila's database.
#   2. Manage the "tulila.service" and "tulila.socket" units.
#      This allows start/stop, but not enable/disable.
# The Polkit rules directory is watched by the daemon and reloaded
# automatically.
cat >/usr/share/polkit-1/rules.d/00-tulila.rules <<'EOF'
polkit.addRule(function(action, subject) {
  if (action.id === "org.freedesktop.systemd1.manage-units"
    && subject.isInGroup("tulila-admins")) {
    var unit = action.lookup("unit");
    if (unit === "tulila.service"
      || unit === "tulila.socket") {
      return polkit.Result.YES;
    }
  }
  return polkit.Result.NOT_HANDLED;
});

polkit.addRule(function(action, subject) {
  if (action.id === "org.freedesktop.policykit.exec"
    && action.lookup("user") === "tulila"
    && subject.isInGroup("tulila-admins")) {
    var program = action.lookup("program");
    if (program === "/opt/tulila/bin/tulila-create-users"
      || program === "/opt/tulila/bin/tulila-export-scores"
      || program === "/opt/tulila/bin/tulila-reset") {
      return polkit.Result.YES;
    }
  }
  return polkit.Result.NOT_HANDLED;
});
EOF

systemctl daemon-reload

echo 'Tulila installed.'
echo
echo 'You must add yourself to the tulila-admins group to manage Tulila (usermod -aG tulila-admins you).'
echo 'NOTE: changes to your groups will not take effect until you log out and back in.'
