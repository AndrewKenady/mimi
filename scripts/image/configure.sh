#!/bin/bash
# Runs inside the new image (in a chroot) during scripts/image/build.sh; not meant for a
# running system. build.sh has already installed the Debian packages, copied
# scripts/image/rootfs/ over the root filesystem and put Mimi's source in /opt/mimi.
#
# Environment (set by build.sh):
#   MIMI_IMAGE_DISK      the whole-disk loop device, for GRUB's BIOS boot code
#   MIMI_IMAGE_ROOT_UUID the root filesystem's UUID, for the EFI boot loader's first step
#   MIMI_IMAGE_TIER      content to include: none (default) or a tier such as lite
#   MIMI_IMAGE_REGION    map region for that content, or for the first-boot download
#   MIMI_IMAGE_FIRST_BOOT  what to download on first boot when the image has no content
#   MIMI_IMAGE_VERSION   the version string recorded in /etc/mimi-image.conf
set -euo pipefail

: "${MIMI_IMAGE_DISK:?}" "${MIMI_IMAGE_VERSION:?}"
tier=${MIMI_IMAGE_TIER:-none}
region=${MIMI_IMAGE_REGION:-}
first_boot=${MIMI_IMAGE_FIRST_BOOT:-lite}
export DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8 HOME=/root

step() { printf '\n== %s\n' "$*"; }

step "Accounts"
# Locked root: no password works, and there's no SSH server to try one on.
usermod --password '*' root
for g in render video dialout; do getent group "$g" >/dev/null || groupadd --system "$g"; done
# mimi runs Mimi Core; kiosk owns the screen session. Neither has a password or a shell.
useradd --system --user-group --home-dir /var/lib/mimi --no-create-home --shell /usr/sbin/nologin \
    --groups render,video,dialout --comment "Mimi Core" mimi
useradd --system --user-group --home-dir /var/lib/kiosk --create-home --shell /usr/sbin/nologin \
    --comment "Mimi kiosk screen" kiosk
install -d -o mimi -g mimi -m 0750 /var/lib/mimi /var/lib/mimi/content /var/lib/mimi/data /var/lib/mimi/logs

step "Mimi (scripts/install.sh --tier none)"
# The same installer as on any Linux machine: uv and Python 3.12, Mimi's packages, the
# engines and the built app, all inside /opt/mimi. Content goes to /var/lib/mimi/content.
export MIMI_CONTENT=/var/lib/mimi/content UV_COMPILE_BYTECODE=1
sh /opt/mimi/scripts/install.sh --tier none
/opt/mimi/python/bin/python -m compileall -q /opt/mimi/core /opt/mimi/scripts /opt/mimi/tools /opt/mimi/.tools/pythons >/dev/null || true

# Every engine must find its libraries in this Debian (the builds target Ubuntu).
missing=$(find /opt/mimi/bin/linux-x64 -type f \( -name 'llama-server' -o -name 'kiwix-serve' -o -name 'pmtiles' -o -name '*.so*' \) \
    -exec ldd {} + 2>/dev/null | grep 'not found' | sort -u || true)
if [ -n "$missing" ]; then
    echo "Engines are missing libraries:" >&2
    echo "$missing" >&2
    exit 1
fi
test -f /opt/mimi/ui/build/index.html || { echo "The app UI wasn't built." >&2; exit 1; }
/opt/mimi/python/bin/python -c "import mimi.app" || { echo "Mimi Core doesn't import." >&2; exit 1; }

# Record what went in, for the build's package list.
mkdir -p /usr/local/share/mimi-image
dpkg-query -W -f '${binary:Package}\t${Version}\n' >/usr/local/share/mimi-image/debian-packages.txt
/opt/mimi/.tools/uv/uv pip freeze --python /opt/mimi/python/bin/python >/usr/local/share/mimi-image/python-packages.txt

# Build-only tools and caches: Node.js and the UI's node_modules, uv and its cache, downloads.
rm -rf /opt/mimi/ui/node_modules /opt/mimi/.tools/node-* /opt/mimi/.tools/uv /opt/mimi/.tools/uv-cache \
    /opt/mimi/.tools/dl /opt/mimi/.tools/core-requirements.txt /root/.npm /root/.cache
chown -R root:root /opt/mimi
chmod -R u+rwX,go+rX,go-w /opt/mimi

if [ "$tier" != none ]; then
    step "Content: $tier${region:+ ($region)}"
    set -- add "$tier" --yes
    [ -n "$region" ] && set -- "$@" --region "$region"
    runuser -u mimi -- env HOME=/var/lib/mimi /opt/mimi/python/bin/mimi content "$@"
    rm -rf /var/lib/mimi/content/.tools/dl
    echo "included in the image: $tier" >/var/lib/mimi/.first-boot-content
    chown mimi:mimi /var/lib/mimi/.first-boot-content
fi

step "Settings"
cat >/etc/mimi-image.conf <<EOF
# Written by scripts/image/build.sh.
MIMI_IMAGE_VERSION=$MIMI_IMAGE_VERSION
MIMI_IMAGE_TIER=$tier
# Downloaded on first boot when the image has no content (none: don't).
MIMI_FIRST_BOOT_CONTENT=$first_boot
MIMI_FIRST_BOOT_REGION=$region
EOF
ln -sf /usr/share/zoneinfo/Etc/UTC /etc/localtime
echo "Etc/UTC" >/etc/timezone
chmod 0755 /usr/local/lib/mimi-image/*

systemctl enable mimi.service mimi-kiosk.service mimi-content.timer mimi-wifi.service \
    mimi-boottest.socket mimi-boottest-console.service mimi-boottest-report.service \
    NetworkManager.service systemd-timesyncd.service
# Nothing runs on tty1 but the kiosk; no automatic apt downloads (update by writing a new image).
systemctl disable getty@tty1.service apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true
systemctl mask apt-daily.service apt-daily-upgrade.service
# No login prompt on a serial port either, even if firmware or a VM puts the console there.
systemctl mask serial-getty@.service console-getty.service
systemctl set-default graphical.target

step "Boot loaders: UEFI (shim, Secure Boot) and BIOS"
# BIOS: GRUB's boot code in the protective MBR and the BIOS boot partition.
grub-install --target=i386-pc --boot-directory=/boot "$MIMI_IMAGE_DISK"
# UEFI: the removable-media path every firmware looks for, \EFI\BOOT\BOOTX64.EFI, holds
# Debian's shim (signed by Microsoft's UEFI CA), which starts Debian's signed GRUB, which
# starts Debian's signed kernel, so Secure Boot can stay on. This is what
# `grub-install --removable --uefi-secure-boot` lays out; it's done by hand because the
# EFI partition is filled from outside (build.sh copies $esp onto it with mtools).
esp=/run/mimi-esp
install -d "$esp/EFI/BOOT" "$esp/EFI/debian" /boot/grub/x86_64-efi
install -m 0644 /usr/lib/shim/shimx64.efi.signed "$esp/EFI/BOOT/BOOTX64.EFI"
install -m 0644 /usr/lib/shim/mmx64.efi.signed "$esp/EFI/BOOT/mmx64.efi"
install -m 0644 /usr/lib/grub/x86_64-efi-signed/grubx64.efi.signed "$esp/EFI/BOOT/grubx64.efi"
cat >"$esp/EFI/BOOT/grub.cfg" <<EOF
search.fs_uuid ${MIMI_IMAGE_ROOT_UUID:?} root
set prefix=(\$root)'/boot/grub'
configfile \$prefix/grub.cfg
EOF
cp "$esp/EFI/BOOT/grub.cfg" "$esp/EFI/debian/grub.cfg"
cp /usr/lib/grub/x86_64-efi/*.mod /usr/lib/grub/x86_64-efi/*.lst /boot/grub/x86_64-efi/
update-initramfs -u -k all
# update-grub names the root filesystem by UUID only if /dev/disk/by-uuid has it, which
# needs udev on the build machine. Without udev it would write the build's loop device.
by_uuid=/dev/disk/by-uuid/$MIMI_IMAGE_ROOT_UUID
made_link=
if [ ! -e "$by_uuid" ]; then
    mkdir -p /dev/disk/by-uuid
    ln -s "${MIMI_IMAGE_DISK}p4" "$by_uuid"
    made_link=1
fi
update-grub
if [ -n "$made_link" ]; then rm -f "$by_uuid"; fi
if grep -E '^\s+linux\s' /boot/grub/grub.cfg | grep -v -q "root=UUID=$MIMI_IMAGE_ROOT_UUID "; then
    echo "grub.cfg doesn't name the root filesystem by its UUID:" >&2
    grep -E '^\s+linux\s' /boot/grub/grub.cfg >&2
    exit 1
fi

step "Clean up"
apt-get clean
rm -rf /var/lib/apt/lists/* /var/cache/apt/*.bin /var/cache/debconf/*-old /tmp/* /var/tmp/*
find /var/log -type f -delete
# Each stick makes its own machine ID and random seed on first boot.
: >/etc/machine-id
rm -f /var/lib/dbus/machine-id /var/lib/systemd/random-seed /etc/resolv.conf
