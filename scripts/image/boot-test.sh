#!/bin/bash
# Boot a Mimi USB image in QEMU and check that it comes up: the same test CI runs.
#
#   scripts/image/boot-test.sh out/mimi-v0.2.0-usb-x86_64.img.xz
#   scripts/image/boot-test.sh mimi.img --firmware bios
#   scripts/image/boot-test.sh --help
#
# The image is attached as a USB stick (xHCI) behind a copy-on-write overlay, so the image
# file is never changed, and the overlay is bigger than the image so first-boot growth is
# exercised. The guest network is isolated from the internet (QEMU's restrict=on), so the
# first-boot download sees "offline". QEMU passes the mimi.boottest credential, which
# opens port 7601 to Mimi Core and copies the guest's journal to the serial port (see
# scripts/image/rootfs/etc/systemd/system/mimi-boottest.*).
#
# Passes when:
#   1. GET /api/ping on Mimi Core answers                       (forwarded port)
#   2. GET / serves the built app, not the "UI hasn't been built" page
#   3. the kiosk session started the browser                    (serial log)
#   4. nothing listens on TCP beyond loopback and the test port (serial log)
#   5. the root filesystem grew to fill the bigger disk         (serial log)
#   6. root's password is locked, and no unit failed            (serial log)
#   7. the first-boot content service ran and saw it was offline (serial log)
#   8. with --firmware uefi-secure, the guest reports Secure Boot enabled (serial log)
# A screenshot of the screen is saved either way.
#
# Needs qemu-system-x86_64, qemu-img, OVMF (UEFI firmware; package ovmf), curl, python3.
# Uses KVM when /dev/kvm is usable, otherwise software emulation (several times slower).
set -euo pipefail

FIRMWARE=uefi
TIMEOUT=
PORT=17600
DISK_GB=16
MEMORY=4096
CPUS=4
OUT=
BUS=usb
IMAGE=

usage() {
    cat <<EOF
Usage: scripts/image/boot-test.sh IMAGE [options]

IMAGE is a .img, .img.xz or .img.zst made by scripts/image/build.sh.

Options:
  --firmware uefi|uefi-secure|bios   UEFI (default), UEFI with Secure Boot enforced and
                                     Microsoft's keys enrolled, or legacy BIOS (SeaBIOS)
  --timeout SECONDS     give up after this long (default: 600 with KVM, 1800 without)
  --port N              host port forwarded to Mimi Core (default: $PORT)
  --disk-gb N           size of the disk the guest sees (default: $DISK_GB)
  --memory MB           guest memory (default: $MEMORY)
  --cpus N              guest CPUs (default: $CPUS)
  --bus usb|virtio      attach the image as a USB stick (default) or a virtio disk
  --out DIR             where the serial log and screenshot go (default: a temporary folder)
  -h, --help            show this help

Environment: OVMF_CODE, OVMF_VARS (firmware files), QEMU (the qemu-system-x86_64 to use).
EOF
}

while [ $# -gt 0 ]; do
    case $1 in
        --firmware) FIRMWARE=$2; shift 2 ;;
        --timeout) TIMEOUT=$2; shift 2 ;;
        --port) PORT=$2; shift 2 ;;
        --disk-gb) DISK_GB=$2; shift 2 ;;
        --memory) MEMORY=$2; shift 2 ;;
        --cpus) CPUS=$2; shift 2 ;;
        --bus) BUS=$2; shift 2 ;;
        --out) OUT=$2; shift 2 ;;
        -h | --help) usage; exit 0 ;;
        -*) echo "Unknown option: $1 (see --help)" >&2; exit 2 ;;
        *) IMAGE=$1; shift ;;
    esac
done

die() { echo "boot-test: $*" >&2; exit 2; }
log() { printf '[%4ds] %s\n' "$(($(date +%s) - T0))" "$*"; }
[ -n "$IMAGE" ] || { usage >&2; exit 2; }
[ -r "$IMAGE" ] || die "can't read $IMAGE"
QEMU=${QEMU:-qemu-system-x86_64}
for tool in "$QEMU" qemu-img curl python3; do command -v "$tool" >/dev/null || die "needs $tool"; done

OUT=${OUT:-$(mktemp -d "${TMPDIR:-/tmp}/mimi-boot-test.XXXXXX")}
mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)
SERIAL=$OUT/serial-$FIRMWARE.log
SHOT=$OUT/screen-$FIRMWARE.png
MONDIR=$(mktemp -d /tmp/mimi-qemu.XXXXXX) # UNIX socket paths must be short
MON=$MONDIR/monitor.sock
: >"$SERIAL"
QPID=
UNPACKED=
cleanup() {
    if [ -n "$QPID" ] && kill -0 "$QPID" 2>/dev/null; then kill "$QPID" 2>/dev/null; sleep 1; kill -9 "$QPID" 2>/dev/null || true; fi
    rm -f "$OUT/overlay-$FIRMWARE.qcow2" "$OUT/vars-$FIRMWARE.fd" ${UNPACKED:+"$UNPACKED"}
    rm -rf "$MONDIR"
}
trap cleanup EXIT
T0=$(date +%s)

# ----------------------------------------------------------------------------- the disk
case $IMAGE in
    *.xz | *.zst)
        RAW=$OUT/disk-$FIRMWARE.img
        UNPACKED=$RAW
        log "decompressing $IMAGE"
        if [ "${IMAGE%.xz}" != "$IMAGE" ]; then xz -dc -T0 "$IMAGE" >"$RAW"; else zstd -dc -q "$IMAGE" >"$RAW"; fi
        ;;
    *) RAW=$(cd "$(dirname "$IMAGE")" && pwd)/$(basename "$IMAGE") ;;
esac
RAW_BYTES=$(stat -c %s "$RAW")
DISK_BYTES=$((DISK_GB * 1024 * 1024 * 1024))
[ "$DISK_BYTES" -gt "$((RAW_BYTES + 2 * 1024 * 1024 * 1024))" ] || die "--disk-gb must be at least 2 GB bigger than the image"
qemu-img create -q -f qcow2 -F raw -b "$RAW" "$OUT/overlay-$FIRMWARE.qcow2" "${DISK_GB}G"

# ----------------------------------------------------------------------------- the machine
args=(-machine q35 -m "$MEMORY" -smp "$CPUS" -display none -vga std
    -serial "file:$SERIAL" -monitor "unix:$MON,server,nowait"
    -netdev "user,id=net0,restrict=on,hostfwd=tcp:127.0.0.1:$PORT-:7601" -device "virtio-net-pci,netdev=net0"
    -smbios "type=11,value=io.systemd.credential:mimi.boottest=1")
if [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
    args+=(-accel kvm -cpu host)
    TIMEOUT=${TIMEOUT:-600}
    log "KVM acceleration"
else
    args+=(-accel tcg -cpu max)
    TIMEOUT=${TIMEOUT:-1800}
    log "no usable /dev/kvm: software emulation, which is slow (timeout ${TIMEOUT}s)"
fi
find_fw() { local f; for f in "$@"; do if [ -r "$f" ]; then echo "$f"; return 0; fi; done; return 1; }
case $FIRMWARE in
    uefi)
        code=${OVMF_CODE:-$(find_fw /usr/share/OVMF/OVMF_CODE_4M.fd /usr/share/OVMF/OVMF_CODE.fd /usr/share/edk2/ovmf/OVMF_CODE.fd /usr/share/qemu/OVMF.fd)} || die "no OVMF firmware (apt-get install ovmf)"
        vars=${OVMF_VARS:-$(find_fw /usr/share/OVMF/OVMF_VARS_4M.fd /usr/share/OVMF/OVMF_VARS.fd /usr/share/edk2/ovmf/OVMF_VARS.fd)} || die "no OVMF variable store"
        cp "$vars" "$OUT/vars-$FIRMWARE.fd"
        args+=(-drive "if=pflash,format=raw,readonly=on,file=$code" -drive "if=pflash,format=raw,file=$OUT/vars-$FIRMWARE.fd")
        ;;
    uefi-secure)
        code=${OVMF_CODE:-$(find_fw /usr/share/OVMF/OVMF_CODE_4M.secboot.fd /usr/share/OVMF/OVMF_CODE.secboot.fd /usr/share/edk2/ovmf/OVMF_CODE.secboot.fd)} || die "no Secure Boot OVMF firmware"
        vars=${OVMF_VARS:-$(find_fw /usr/share/OVMF/OVMF_VARS_4M.ms.fd /usr/share/OVMF/OVMF_VARS.ms.fd /usr/share/edk2/ovmf/OVMF_VARS.secboot.fd)} || die "no OVMF variable store with Microsoft's keys"
        cp "$vars" "$OUT/vars-$FIRMWARE.fd"
        args[1]=q35,smm=on
        args+=(-global "driver=cfi.pflash01,property=secure,value=on"
            -drive "if=pflash,format=raw,unit=0,readonly=on,file=$code" -drive "if=pflash,format=raw,unit=1,file=$OUT/vars-$FIRMWARE.fd")
        ;;
    bios) ;; # QEMU's default firmware is SeaBIOS
    *) die "--firmware must be uefi, uefi-secure or bios" ;;
esac
case $BUS in
    usb) args+=(-drive "if=none,id=stick,format=qcow2,file=$OUT/overlay-$FIRMWARE.qcow2" -device "qemu-xhci,id=xhci"
        -device "usb-storage,bus=xhci.0,drive=stick,removable=on,bootindex=0") ;;
    virtio) args+=(-drive "if=virtio,format=qcow2,file=$OUT/overlay-$FIRMWARE.qcow2") ;;
    *) die "--bus must be usb or virtio" ;;
esac

monitor() { # Send one command to the QEMU monitor.
    python3 - "$MON" "$1" <<'EOF'
import socket, sys, time
s = socket.socket(socket.AF_UNIX)
s.connect(sys.argv[1])
s.sendall(sys.argv[2].encode() + b"\n")
time.sleep(2)
s.close()
EOF
}
screenshot() {
    rm -f "$SHOT"
    monitor "screendump $SHOT -f png" 2>/dev/null || true
    if [ -s "$SHOT" ]; then log "screenshot: $SHOT"; fi
}
seen() { grep -a -q -- "$1" "$SERIAL"; }
alive() { kill -0 "$QPID" 2>/dev/null; }

log "booting $(basename "$IMAGE") ($((RAW_BYTES / 1048576)) MiB) as a ${DISK_GB} GB $BUS disk, $FIRMWARE firmware"
"$QEMU" "${args[@]}" &
QPID=$!

# ----------------------------------------------------------------------------- wait
ping_s=
deadline=$((T0 + TIMEOUT))
while alive && [ "$(date +%s)" -lt "$deadline" ]; do
    if [ -z "$ping_s" ] && body=$(curl -fsS --max-time 5 "http://127.0.0.1:$PORT/api/ping" 2>/dev/null); then
        ping_s=$(($(date +%s) - T0))
        log "Mimi Core answered /api/ping after ${ping_s}s: $body"
    fi
    if [ -n "$ping_s" ] && seen "mimi-boottest: report-done" && seen "mimi-kiosk: opening" && seen "mimi-content: "; then
        break
    fi
    sleep 5
done
alive || log "QEMU exited early"
if seen "mimi-kiosk: opening"; then sleep 45; fi # give the browser time to draw the app
screenshot

# ----------------------------------------------------------------------------- checks
fails=0
check() { # description, then a command that succeeds when it holds
    local what=$1
    shift
    if "$@"; then echo "  ok    $what"; else echo "  FAIL  $what"; fails=$((fails + 1)); fi
}
report() { grep -a -o "mimi-boottest: $1.*" "$SERIAL" | sed "s/^mimi-boottest: $1 *//" | tr -d '\r'; }
ui_built() { # not curl | grep -q: with pipefail, grep stopping early fails curl
    local page
    page=$(curl -fsS --max-time 20 "http://127.0.0.1:$PORT/" 2>/dev/null) || return 1
    [[ $page == *_app/immutable* ]]
}
grew() { local b; b=$(report root-bytes | head -n 1); [ -n "$b" ] && [ "$b" -gt "$((DISK_BYTES * 8 / 10))" ]; }
loopback_only() {
    local bad
    bad=$(report tcp-listen | grep -v -E '^(127\.[0-9.]+|\[::1\]|\[::ffff:127\.[0-9.]+\]):[0-9]+$' | grep -v -E ':7601$' || true)
    [ -z "$bad" ] || { echo "        listening beyond loopback: $(echo "$bad" | xargs)"; return 1; }
    [ -n "$(report tcp-listen)" ]
}
root_locked() { [ "$(report root-password | head -n 1)" = L ]; }
no_failed_units() {
    local f
    f=$(report failed | xargs)
    [ -z "$f" ] || { echo "        failed units: $f"; return 1; }
    seen "mimi-boottest: report-done"
}

echo
echo "Boot test, $FIRMWARE firmware ($(basename "$IMAGE")):"
check "Mimi Core answers GET /api/ping${ping_s:+ (after ${ping_s}s)}" test -n "$ping_s"
check "GET / serves the built app" ui_built
check "the kiosk session opened the browser" seen "mimi-kiosk: opening"
check "nothing listens on TCP beyond loopback (and the test port)" loopback_only
check "the root filesystem grew to fill the ${DISK_GB} GB disk ($(report root-bytes | head -n 1) bytes)" grew
check "root's password is locked" root_locked
check "no systemd unit failed" no_failed_units
check "the first-boot download ran and found no network" seen "mimi-content: offline"
if [ "$FIRMWARE" = uefi-secure ]; then
    check "Secure Boot was on ($(report secure-boot | head -n 1))" seen "mimi-boottest: secure-boot SecureBoot enabled"
fi
for line in $(report doctor | tr ' ' '_'); do echo "  info  doctor ${line//_/ }"; done
echo
echo "Serial log: $SERIAL"
if [ -s "$SHOT" ]; then echo "Screenshot: $SHOT"; fi
if [ "$fails" -gt 0 ]; then
    echo "boot-test: $fails check(s) failed. The guest's journal is in the serial log."
    exit 1
fi
echo "boot-test: passed in $(($(date +%s) - T0))s"
