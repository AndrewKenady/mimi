#!/bin/bash
# Build Mimi's bootable USB image: a minimal Debian (stable) that starts straight into
# Mimi, full screen, on any x86-64 PC (UEFI with Secure Boot, or legacy BIOS).
#
#   sudo scripts/image/build.sh                          # no content (what CI publishes)
#   sudo scripts/image/build.sh --tier lite --region uk  # Lite tier included: a fully offline stick
#   scripts/image/build.sh --help
#
# Needs root (loop devices, mounts, chroot) on Debian 12+ or Ubuntu 22.04+ with:
#   apt-get install mmdebstrap debian-archive-keyring dosfstools mtools e2fsprogs fdisk xz-utils zstd
# The FAT partitions are filled with mtools, so the host kernel doesn't need FAT support.
#
# Steps, each a function below:
#   partition   a sparse disk image: BIOS boot, EFI system (FAT), MIMI settings (FAT), root (ext4)
#   bootstrap   Debian with mmdebstrap, exactly the packages in scripts/image/packages.txt
#   configure   copy scripts/image/rootfs/ and Mimi's source in, then run scripts/image/configure.sh
#               inside: accounts, scripts/install.sh --tier none, services, GRUB (UEFI and BIOS)
#   shrink      the root filesystem to its contents plus some room (it grows to fill the stick
#               on first boot) and the image file with it
#   compress    xz (or zstd), a .sha256 and the lists of Debian and Python packages
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)

OUT=${TMPDIR:-/var/tmp}/mimi-image
TIER=none
REGION=
FIRST_BOOT=lite
SUITE=trixie
MIRROR=http://deb.debian.org/debian
SECURITY_MIRROR=http://deb.debian.org/debian-security
REF=HEAD
NAME=
COMPRESS=xz
KEEP_RAW=0
SLACK_MB=768
WORK_GB=
CA_CERT=${SSL_CERT_FILE:-}

usage() {
    cat <<EOF
Usage: sudo scripts/image/build.sh [options]

Builds a disk image that boots any x86-64 PC (UEFI or BIOS) straight into Mimi, full
screen. Write it to a USB stick (8 GB or larger) with dd, Rufus or balenaEtcher.

Options:
  --out DIR           where the image and its checksum go (default: $OUT)
  --tier TIER         content to include: none (default), lite, standard, plus or max.
                      A tier makes a big image (lite: about 25 GB); build those locally.
  --region NAME       map region for --tier, or for the first-boot download
                      (python3 scripts/content.py regions; default: the tier's own)
  --first-boot TIER   with --tier none: what the stick downloads by itself on first boot
                      when it's online (default: lite; none to turn this off)
  --ref REF           the git commit, branch or tag of Mimi to install (default: HEAD)
  --name NAME         file name without extension (default: mimi-<version>-usb-x86_64)
  --compress FORMAT   xz (default; Rufus, balenaEtcher and dd all read it), zstd or none
  --keep-raw          keep the uncompressed .img next to the compressed one
  --suite NAME        Debian release (default: $SUITE)
  --mirror URL        Debian mirror (default: $MIRROR)
  --security-mirror URL   (default: $SECURITY_MIRROR)
  --ca-cert FILE      extra CA bundle for downloads during the build, e.g. behind a TLS-inspecting
                      proxy (default: \$SSL_CERT_FILE if set). It is not copied into the image.
  --work-gb N         size of the sparse working image in GB (default: 15, or more for a tier)
  -h, --help          show this help

HTTPS_PROXY/NO_PROXY are passed through to the downloads inside the image.
The result: <out>/<name>.img.xz, <name>.img.xz.sha256 and <name>.packages.txt.
Boot-test it with scripts/image/boot-test.sh <out>/<name>.img.xz.
EOF
}

while [ $# -gt 0 ]; do
    case $1 in
        --out) OUT=$2; shift 2 ;;
        --tier) TIER=$2; shift 2 ;;
        --region) REGION=$2; shift 2 ;;
        --first-boot) FIRST_BOOT=$2; shift 2 ;;
        --ref) REF=$2; shift 2 ;;
        --name) NAME=$2; shift 2 ;;
        --compress) COMPRESS=$2; shift 2 ;;
        --keep-raw) KEEP_RAW=1; shift ;;
        --suite) SUITE=$2; shift 2 ;;
        --mirror) MIRROR=$2; shift 2 ;;
        --security-mirror) SECURITY_MIRROR=$2; shift 2 ;;
        --ca-cert) CA_CERT=$2; shift 2 ;;
        --work-gb) WORK_GB=$2; shift 2 ;;
        -h | --help) usage; exit 0 ;;
        *) echo "Unknown option: $1 (see --help)" >&2; exit 2 ;;
    esac
done

die() { echo "build.sh: $*" >&2; exit 1; }
step() { printf '\n==== %s  [%s]\n' "$*" "$(date -u +%H:%M:%S)"; }

case $COMPRESS in xz | zstd | none) ;; *) die "--compress must be xz, zstd or none" ;; esac
case $TIER in
    none) ;;
    lite | standard | plus | max) FIRST_BOOT=none ;;
    *) die "--tier must be none, lite, standard, plus or max" ;;
esac
[ "$(id -u)" = 0 ] || die "needs root for loop devices, mounts and chroot: run it with sudo"
for tool in mmdebstrap sfdisk losetup partx mkfs.vfat mkfs.ext4 e2fsck resize2fs dumpe2fs mcopy git; do
    command -v "$tool" >/dev/null || die "needs $tool (apt-get install mmdebstrap dosfstools mtools e2fsprogs fdisk git)"
done
[ "$COMPRESS" = none ] || command -v "$COMPRESS" >/dev/null || die "needs $COMPRESS"
[ -z "$CA_CERT" ] || [ -r "$CA_CERT" ] || die "can't read the CA bundle $CA_CERT"

if [ -z "$WORK_GB" ]; then
    case $TIER in none) WORK_GB=15 ;; lite) WORK_GB=48 ;; *) WORK_GB=400 ;; esac
fi
COMMIT=$(git -C "$REPO" rev-parse --verify "$REF^{commit}") || die "no such git ref: $REF"
VERSION=$(git -C "$REPO" describe --tags --always "$COMMIT" 2>/dev/null || git -C "$REPO" rev-parse --short "$COMMIT")
if [ -z "$NAME" ]; then
    NAME=mimi-$VERSION-usb-x86_64
    if [ "$TIER" != none ]; then NAME=$NAME-$TIER${REGION:+-$REGION}; fi
fi
mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)
WORK=$OUT/.work-$NAME
IMG=$OUT/$NAME.img
MNT=$WORK/root
LOOP=
MADE_NODES=()
RAW_BYTES=0
ROOT_UUID=

# --------------------------------------------------------------------------- cleanup
cleanup() {
    set +e
    if [ -d "$MNT" ]; then
        for m in $(findmnt -rno TARGET | grep -F "$MNT" | sort -r); do umount "$m" 2>/dev/null || umount -l "$m"; done
    fi
    [ -n "$LOOP" ] && losetup -d "$LOOP" 2>/dev/null
    for n in "${MADE_NODES[@]}"; do rm -f "$n"; done
    LOOP=
    MADE_NODES=()
}
trap cleanup EXIT
trap 'exit 130' INT TERM

attach() { # Attach $IMG to a loop device with partition nodes (made by hand where there's no udev).
    LOOP=$(losetup --show --find --partscan "$IMG")
    partx --add "$LOOP" 2>/dev/null || true # in case the kernel's own scan missed them
    if command -v udevadm >/dev/null; then udevadm settle 2>/dev/null || true; fi
    local n p dev mm
    n=$(basename "$LOOP")
    for p in 1 2 3 4; do
        dev=${LOOP}p$p
        for _ in 1 2 3 4 5 6 7 8 9 10; do [ -b "$dev" ] && break; sleep 0.5; done
        if [ ! -b "$dev" ]; then
            [ -r "/sys/class/block/${n}p$p/dev" ] || die "the kernel didn't see partition $p of $LOOP"
            mm=$(cat "/sys/class/block/${n}p$p/dev")
            mknod "$dev" b "${mm%%:*}" "${mm##*:}"
            MADE_NODES+=("$dev")
        fi
    done
}

detach() {
    losetup -d "$LOOP"
    for n in "${MADE_NODES[@]}"; do rm -f "$n"; done
    LOOP=
    MADE_NODES=()
}

# --------------------------------------------------------------------------- 1. partition
partition() {
    step "Partition a ${WORK_GB} GB sparse image: $IMG"
    rm -rf "$WORK" "$IMG" "$IMG".*
    mkdir -p "$MNT"
    truncate -s "${WORK_GB}G" "$IMG"
    # GPT: BIOS boot (GRUB's BIOS code), EFI system partition, a small FAT partition that
    # Windows and macOS can open (wifi.txt), and the root filesystem last so it can grow.
    sfdisk --quiet "$IMG" <<EOF
label: gpt
size=1MiB, type=21686148-6449-6E6F-744E-656564454649, name="bios-boot"
size=127MiB, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B, name="EFI system"
size=32MiB, type=EBD0A0A2-B9E5-4433-87C0-68B6B72699C7, name="mimi-settings"
type=4F68BCE3-E8CD-4DB1-96E7-FBCAF984B709, name="mimi-root"
EOF
    attach
    mkfs.vfat -F 32 -n EFI "${LOOP}p2" >/dev/null
    mkfs.vfat -F 16 -n MIMI "${LOOP}p3" >/dev/null
    # lazy_itable_init + noinit_itable: inode tables of the (big, sparse) working filesystem
    # are never written, so it costs only the space it holds. A fixed 128 MiB journal.
    mkfs.ext4 -q -L mimi-root -J size=128 -E lazy_itable_init=1,lazy_journal_init=1,nodiscard "${LOOP}p4"
    mount -o noinit_itable "${LOOP}p4" "$MNT"
}

# --------------------------------------------------------------------------- 2. bootstrap
bootstrap() {
    step "Debian $SUITE with mmdebstrap"
    local packages
    packages=$(sed -e 's/#.*//' "$HERE/packages.txt" | xargs | tr ' ' ',')
    local keyring=()
    if [ -r /usr/share/keyrings/debian-archive-keyring.gpg ]; then
        keyring=(--keyring=/usr/share/keyrings/debian-archive-keyring.gpg)
    fi
    # Documentation and man pages are left out, except each package's copyright file.
    mmdebstrap --mode=root --variant=apt --format=directory "${keyring[@]}" \
        --aptopt='APT::Install-Recommends "false"' \
        --dpkgopt='path-exclude=/usr/share/doc/*' --dpkgopt='path-include=/usr/share/doc/*/copyright' \
        --dpkgopt='path-exclude=/usr/share/man/*' --dpkgopt='path-exclude=/usr/share/info/*' \
        --include="$packages" \
        "$SUITE" "$MNT" \
        "deb $MIRROR $SUITE main non-free-firmware" \
        "deb $MIRROR $SUITE-updates main non-free-firmware" \
        "deb $SECURITY_MIRROR $SUITE-security main non-free-firmware"
}

# --------------------------------------------------------------------------- 3. configure
in_root() { # Run a command inside the image with the network and build settings it needs.
    local env=(PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
        "MIMI_IMAGE_DISK=$LOOP" "MIMI_IMAGE_ROOT_UUID=$ROOT_UUID" "MIMI_IMAGE_TIER=$TIER"
        "MIMI_IMAGE_REGION=$REGION" "MIMI_IMAGE_FIRST_BOOT=$FIRST_BOOT" "MIMI_IMAGE_VERSION=$VERSION")
    local v
    for v in HTTPS_PROXY https_proxy HTTP_PROXY http_proxy NO_PROXY no_proxy npm_config_https_proxy npm_config_noproxy; do
        if [ -n "${!v:-}" ]; then env+=("$v=${!v}"); fi
    done
    if [ -n "$CA_CERT" ]; then
        env+=(SSL_CERT_FILE=/run/mimi-build-ca.pem CURL_CA_BUNDLE=/run/mimi-build-ca.pem
            NODE_EXTRA_CA_CERTS=/run/mimi-build-ca.pem PIP_CERT=/run/mimi-build-ca.pem
            REQUESTS_CA_BUNDLE=/run/mimi-build-ca.pem)
    fi
    chroot "$MNT" /usr/bin/env -i "${env[@]}" "$@"
}

configure() {
    step "Configure: rootfs overlay, Mimi $VERSION ($COMMIT), services, boot loaders"
    cp -R "$HERE/rootfs/." "$MNT/"
    mkdir -p "$MNT/usr/local/share/mimi-image/settings" "$MNT/opt/mimi"
    cp "$HERE/settings/README.txt" "$HERE/settings/wifi.txt" "$MNT/usr/local/share/mimi-image/settings/"
    git -C "$REPO" archive --format=tar "$COMMIT" | tar -x -C "$MNT/opt/mimi"

    ROOT_UUID=$(blkid -s UUID -o value "${LOOP}p4")
    cat >"$MNT/etc/fstab" <<EOF
# <file system>  <mount point>  <type>  <options>  <dump>  <pass>
UUID=$ROOT_UUID  /  ext4  defaults,noatime,errors=remount-ro,x-systemd.growfs  0  1
EOF

    mount -t proc proc "$MNT/proc"
    mount -t sysfs sysfs "$MNT/sys"
    mount --bind /dev "$MNT/dev"
    mount -t devpts devpts "$MNT/dev/pts" -o gid=5,mode=620,ptmxmode=666 2>/dev/null || mount --bind /dev/pts "$MNT/dev/pts"
    mount -t tmpfs tmpfs "$MNT/run"
    cp -L /etc/resolv.conf "$MNT/etc/resolv.conf"
    if [ -n "$CA_CERT" ]; then cp "$CA_CERT" "$MNT/run/mimi-build-ca.pem"; fi
    cp "$HERE/configure.sh" "$MNT/run/mimi-configure.sh"

    in_root /bin/bash /run/mimi-configure.sh

    # The two FAT partitions are filled with mtools, so the build never mounts FAT.
    export MTOOLS_SKIP_CHECK=1
    mcopy -s -i "${LOOP}p2" "$MNT/run/mimi-esp/EFI" ::/
    mcopy -i "${LOOP}p3" "$HERE/settings/README.txt" "$HERE/settings/wifi.txt" ::/
    echo "EFI system partition:"
    mdir -/ -b -i "${LOOP}p2" ::/

    {
        echo "# $NAME: Mimi $VERSION ($COMMIT), Debian $SUITE, built $(date -u +%Y-%m-%d)"
        echo "# Debian packages"
        cat "$MNT/usr/local/share/mimi-image/debian-packages.txt"
        echo
        echo "# Python packages in /opt/mimi/python"
        cat "$MNT/usr/local/share/mimi-image/python-packages.txt"
    } >"$OUT/$NAME.packages.txt"

    # Unmounting /run removes the build's CA bundle and scripts with it.
    for m in $(findmnt -rno TARGET | grep -F "$MNT/" | sort -r); do umount "$m"; done
    fstrim "$MNT" 2>/dev/null || true # deleted build files become holes, which compress to nothing
    df -h "$MNT"
    umount "$MNT"
}

# --------------------------------------------------------------------------- 4. shrink
shrink() {
    step "Shrink the root filesystem and the image"
    local part=${LOOP}p4 rc=0
    e2fsck -fy "$part" || rc=$?
    [ "$rc" -le 1 ] || die "e2fsck found problems it couldn't fix (exit $rc)"
    local bs min want
    bs=$(dumpe2fs -h "$part" 2>/dev/null | awk -F: '/^Block size/ { gsub(/ /, "", $2); print $2 }')
    min=$(resize2fs -P "$part" 2>/dev/null | awk -F': ' '/minimum size/ { print $2 }')
    want=$((min + SLACK_MB * 1024 * 1024 / bs))
    # Whole MiB, so the partition ends on a 1 MiB boundary.
    want=$(((want * bs + 1048575) / 1048576 * 1048576 / bs))
    resize2fs "$part" "$want"
    detach

    # Cut the image after the root partition (plus 1 MiB for the backup partition table)
    # and write the same table again for the new size: same disk and partition IDs, types,
    # names and starts, only the root partition shorter. GRUB's boot code in the first
    # 440 bytes is put back in case the new protective MBR overwrote it.
    local table start sectors
    table=$(sfdisk --dump "$IMG")
    start=$(sed -n '/name="mimi-root"/ s/.*start= *\([0-9]*\).*/\1/p' <<<"$table")
    sectors=$((want * bs / 512))
    [ -n "$start" ] || die "can't find the root partition in the partition table"
    dd if="$IMG" of="$WORK/mbr-code" bs=440 count=1 status=none
    truncate -s $(((start + sectors + 2048) * 512)) "$IMG"
    grep -v '^last-lba:' <<<"$table" | sed "/name=\"mimi-root\"/ s/size= *[0-9]*/size=$sectors/" |
        sfdisk --quiet --wipe never --wipe-partitions never --no-reread --no-tell-kernel "$IMG"
    dd if="$WORK/mbr-code" of="$IMG" bs=440 count=1 conv=notrunc status=none
    sfdisk --verify "$IMG"
    [ "$(sfdisk --dump "$IMG" | grep -c -E '^label: gpt$|name="(bios-boot|EFI system|mimi-settings|mimi-root)"')" = 5 ] ||
        die "the partition table didn't survive shrinking"
    RAW_BYTES=$(stat -c %s "$IMG")
    echo "root filesystem: $((want * bs / 1048576)) MiB; image: $((RAW_BYTES / 1048576)) MiB"
}

# --------------------------------------------------------------------------- 5. compress
compress() {
    local file=$IMG
    case $COMPRESS in
        xz) step "Compress (xz)"; xz -T0 -6 -k -f "$IMG"; file=$IMG.xz ;;
        zstd) step "Compress (zstd)"; zstd -T0 -19 --long=27 -q -f "$IMG" -o "$IMG.zst"; file=$IMG.zst ;;
    esac
    if [ "$COMPRESS" != none ] && [ "$KEEP_RAW" = 0 ]; then rm -f "$IMG"; fi
    (cd "$OUT" && sha256sum "$(basename "$file")" >"$(basename "$file").sha256")
    rm -rf "$WORK"
    step "Done"
    ls -l "$OUT/$NAME".*
    echo
    echo "Raw image: $((RAW_BYTES / 1048576)) MiB (what gets written to the stick)"
    echo "File:      $file ($(($(stat -c %s "$file") / 1048576)) MiB)"
    echo "Checksum:  $(cat "$file.sha256")"
    echo "Boot test: scripts/image/boot-test.sh $file"
}

partition
bootstrap
configure
shrink
compress
