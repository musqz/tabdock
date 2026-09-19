#!/usr/bin/env bash
# Installs the native-messaging manifest so the browser can start the relay.
# M1 dev install: the manifest points at this checkout. Native browsers only
# (no Flatpak/Snap). More browsers and a real ~/.local install come later.
#
#   ./install.sh              install
#   ./install.sh --uninstall  remove exactly what install created
set -euo pipefail

root="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
host="$root/lib/native-host/sidepanel-nmhost"
template="$root/configs/openbox_sidepanel.json.in"
manifest_name="openbox_sidepanel.json"

shopt -u patsub_replacement 2>/dev/null || true  # keep '&' in paths literal

# browser -> native-messaging-hosts dir
declare -A targets=(
    [firefox]="$HOME/.mozilla/native-messaging-hosts"
)

action=install
case "${1:-}" in
    "") ;;
    --uninstall) action=uninstall ;;
    *) echo "usage: $0 [--uninstall]" >&2; exit 2 ;;
esac

for browser in "${!targets[@]}"; do
    dir="${targets[$browser]}"
    file="$dir/$manifest_name"

    if [[ $action == uninstall ]]; then
        if [[ -e $file ]]; then
            rm -- "$file"
            echo "removed   $file"
        else
            echo "absent    $file"
        fi
        continue
    fi

    [[ -x $host ]] || { echo "error: $host is not executable" >&2; exit 1; }
    mkdir -p -- "$dir"
    verb=installed
    [[ -e $file ]] && verb=updated
    content="$(<"$template")"
    printf '%s\n' "${content//@HOST_PATH@/$host}" > "$file"
    python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$file" \
        || { echo "error: $file is not valid JSON" >&2; exit 1; }
    echo "$verb $file ($browser) -> $host"
done
