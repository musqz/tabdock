#!/usr/bin/env bash
# Installs tabdock for native browsers (Firefox, Zen, ...; no Flatpak/Snap).
#
#   ./install.sh                          install to ~/.local (bin/tabdock, share/tabdock)
#   PREFIX=/usr SUDO=sudo ./install.sh    program files system-wide (manifests stay per-user)
#   ./install.sh --uninstall              remove exactly what install created
#
# Installed under $PREFIX/share/tabdock, with $PREFIX/bin/tabdock linking to it, plus the
# native-messaging manifest that lets the browser start the relay. Nothing outside those
# paths is touched (your Openbox autostart is only mentioned, never edited).
set -euo pipefail

shopt -u patsub_replacement 2>/dev/null || true  # keep '&' in paths literal

root="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
PREFIX="${PREFIX:-$HOME/.local}"
SUDO="${SUDO:-}"
share="$PREFIX/share/tabdock"
bin="$PREFIX/bin/tabdock"
relay="$share/lib/native-host/tabdock-nmhost"
receipt="$share/.installed"  # every path install created, one per line: what --uninstall removes
manifest_name="openbox_sidepanel.json"  # named by the extension, which kept its name through the rename
apps_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
desktop_name="tabdock.desktop"
# an install from before the rename to tabdock: installing removes it, and so does --uninstall
old_share="$PREFIX/share/openbox-sidepanel"
old_bin="$PREFIX/bin/sidepanel"
old_receipt="$old_share/.installed"
# native-messaging manifest dirs. One manifest in ~/.mozilla serves Firefox, Zen, FireDragon,
# Waterfox and LibreWolf: each was verified with tests/e2e_firefox.py --firefox <browser>.
nm_dirs=("$HOME/.mozilla/native-messaging-hosts")

installed=()

die() { echo "error: $*" >&2; exit 1; }

# put MODE SRC DEST: install one file, saying whether it was new, changed or already current
put() {
    local mode=$1 src=$2 dest=$3 verb=installed
    [[ -f $src ]] || die "missing source file $src"
    if [[ -e $dest ]]; then
        if cmp -s -- "$src" "$dest"; then verb=unchanged; else verb=updated; fi
    fi
    if [[ $verb != unchanged ]]; then
        $SUDO install -Dm"$mode" -- "$src" "$dest"
    fi
    printf '%-10s %s\n' "$verb" "$dest"
    installed+=("$dest")
}

remove() {
    local path=$1
    if [[ -e $path || -L $path ]]; then
        $SUDO rm -f -- "$path"
        printf '%-10s %s\n' removed "$path"
    else
        printf '%-10s %s\n' absent "$path"
    fi
}

# remove a path a receipt lists, except a command that no longer links to the install it came from
# (repointed by hand, e.g. to a dev checkout)
remove_listed() {
    local path=$1
    if [[ ( $path == "$bin" && ! ( -L $path && "$(readlink -- "$path")" == "$share/tabdock" ) ) ||
          ( $path == "$old_bin" && ! ( -L $path && "$(readlink -- "$path")" == "$old_share/sidepanel" ) ) ]]; then
        printf '%-10s %s (not a link to this install)\n' skipped "$path"
    else
        remove "$path"
    fi
}

# bytecode written by the installed copy, then any directories left empty
tidy() {
    [[ -d $1 ]] || return 0
    $SUDO find "$1" -name __pycache__ -type d -prune -exec rm -rf {} +
    $SUDO find "$1" -depth -type d -empty -delete
}

install_files() {
    local f
    put 755 "$root/tabdock" "$share/tabdock"
    put 644 "$root/VERSION" "$share/VERSION"
    # the whole package tree, so a new module or subpackage is never left out of the installed copy
    while IFS= read -r -d '' f; do
        put 644 "$f" "$share/lib/tabdock/${f#"$root"/lib/tabdock/}"
    done < <(find "$root/lib/tabdock" -type f -not -path '*/__pycache__/*' -print0 | sort -z)
    put 755 "$root/lib/native-host/tabdock-nmhost" "$relay"
    put 644 "$root/configs/config.toml" "$share/configs/config.toml"
    put 644 "$root/extension/icons/icon-96.png" "$share/icon.png"  # for the menu entry
}

link_bin() {
    local target="$share/tabdock" note=
    if [[ -L $bin && "$(readlink -- "$bin")" == "$target" ]]; then
        printf '%-10s %s\n' unchanged "$bin"
        installed+=("$bin")
        return
    fi
    if [[ -f $bin && ! -L $bin ]] && cmp -s -- "$root/tabdock" "$bin"; then
        # A launcher copied there by hand can never find its files. It is identical to ours,
        # so replacing it with the link loses nothing.
        $SUDO rm -f -- "$bin"
        note=" (replaced an identical hand-copied launcher)"
    elif [[ -e $bin || -L $bin ]]; then
        die "$bin already exists and is not this install (a hand-copied or different launcher?); remove or move it first"
    fi
    $SUDO mkdir -p -- "${bin%/*}"
    $SUDO ln -s -- "$target" "$bin"
    printf '%-10s %s -> %s%s\n' installed "$bin" "$target" "$note"
    installed+=("$bin")
}

write_manifests() {
    local dir file content
    content="$(<"$root/configs/openbox_sidepanel.json.in")"
    content="${content//@HOST_PATH@/$relay}"
    for dir in "${nm_dirs[@]}"; do
        file="$dir/$manifest_name"
        if [[ -e $file && "$(<"$file")" == "$content" ]]; then
            printf '%-10s %s\n' unchanged "$file"
        else
            local verb=installed
            [[ -e $file ]] && verb=updated
            mkdir -p -- "$dir"
            printf '%s\n' "$content" > "$file"
            printf '%-10s %s\n' "$verb" "$file"
        fi
        python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$file" || die "$file is not valid JSON"
        installed+=("$file")
    done
}

# A path as a Desktop Entry Exec value: '%' doubled (it starts a field code) and the path quoted
# when it holds a character launchers would split on. Characters that need backslash escaping
# inside quotes (" ` $ \) are not supported: return 1 and the caller skips the entry.
desktop_exec() {
    local p="${1//%/%%}"
    case $p in
        *[\"\`\$\\]*) return 1 ;;
        *[[:space:]\;\<\>~\|\&\'*?#\(\)]*) printf '"%s"' "$p" ;;
        *) printf '%s' "$p" ;;
    esac
}

# A menu entry so the panel can be started without a terminal (jgmenu, rofi, ... read these).
write_desktop_entry() {
    local file="$apps_dir/$desktop_name" content verb=installed exec_value
    exec_value="$(desktop_exec "$bin")" || {
        echo "warning: $bin has characters a menu entry cannot express; skipping the menu entry" >&2
        return 0
    }
    content="$(<"$root/configs/tabdock.desktop.in")"
    content="${content//@BIN@/$exec_value}"
    content="${content//@ICON@/$share/icon.png}"
    if [[ -e $file && "$(<"$file")" == "$content" ]]; then
        printf '%-10s %s\n' unchanged "$file"
    else
        [[ -e $file ]] && verb=updated
        mkdir -p -- "$apps_dir"
        printf '%s\n' "$content" > "$file"
        printf '%-10s %s\n' "$verb" "$file"
    fi
    if command -v desktop-file-validate > /dev/null; then
        desktop-file-validate "$file" || echo "warning: desktop-file-validate complains about $file" >&2
    fi
    installed+=("$file")
}

# files an earlier version installed that this one no longer ships, including a whole install from
# before the rename to tabdock
remove_stale() {
    local list old path keep
    for list in "$receipt" "$old_receipt"; do
        [[ -f $list ]] || continue
        while IFS= read -r old; do
            keep=
            for path in "${installed[@]}"; do [[ $path == "$old" ]] && keep=1; done
            [[ -n $keep ]] || remove_listed "$old"
        done < "$list"
    done
    if [[ -f $old_receipt ]]; then
        remove "$old_receipt"
        tidy "$old_share"
    fi
}

# The command was called sidepanel before the rename: say where it is still started by that name.
mention_old_command() {
    local file files=() found
    for file in "${XDG_CONFIG_HOME:-$HOME/.config}"/openbox/{autostart,rc.xml}; do
        [[ -f $file ]] && files+=("$file")
    done
    (( ${#files[@]} )) || return 0
    found="$(grep -Hn -E -- '(^|[^[:alnum:]_.-])sidepanel([^[:alnum:]_.-]|$)' "${files[@]}")" || return 0
    echo "warning: the command is tabdock now; these lines still start it as sidepanel:" >&2
    sed 's/^/  /' <<< "$found" >&2
}

write_receipt() {
    local tmp
    tmp="$(mktemp)"
    printf '%s\n' "${installed[@]}" > "$tmp"
    $SUDO install -Dm644 -- "$tmp" "$receipt"
    rm -f -- "$tmp"
}

verify() {
    local out
    # no bytecode: it would put files into the install that the receipt does not list
    out="$(PYTHONDONTWRITEBYTECODE=1 "$bin" --version)" || die "$bin does not run"
    printf '%-10s %s\n' verified "$out"
    case ":$PATH:" in
        *":${bin%/*}:"*) ;;
        *) echo "warning: ${bin%/*} is not in your PATH" >&2 ;;
    esac
}

do_install() {
    command -v python3 > /dev/null || die "python3 not found"
    install_files
    link_bin
    write_manifests
    write_desktop_entry
    remove_stale
    write_receipt
    verify
    mention_old_command
    cat <<EOF

Next:
  1. Install the signed browser extension: see docs/RELEASE.md
  2. Starting the panel, any of these:
       - it starts by itself when a browser with the extension opens (start_with_browser in config.toml)
       - "Tabdock" in your application menu
       - at login: add this line to ~/.config/openbox/autostart, after picom starts:
             (sleep 5.0s && $(printf '%q' "$bin")) &
EOF
}

do_uninstall() {
    local path dir file target
    if [[ -f $receipt ]]; then
        while IFS= read -r path; do remove_listed "$path"; done < "$receipt"
        remove "$receipt"
    else
        printf '%-10s %s (nothing installed there)\n' absent "$receipt"
    fi
    if [[ -f $old_receipt ]]; then
        while IFS= read -r path; do remove_listed "$path"; done < "$old_receipt"
        remove "$old_receipt"
    fi
    # The browser manifest: remove it when it points at this install's relay, even without a
    # receipt; keep it (and say so) when it belongs to an install under another PREFIX.
    for dir in "${nm_dirs[@]}"; do
        file="$dir/$manifest_name"
        [[ -e $file ]] || continue
        target="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("path", ""))' "$file" 2> /dev/null || true)"
        if [[ $target == "$relay" || $target == "$old_share/lib/native-host/sidepanel-nmhost" ]]; then
            remove "$file"
        else
            printf '%-10s %s (points at %s: uninstall with the PREFIX it was installed with)\n' kept "$file" "${target:-?}" >&2
        fi
    done
    tidy "$share"
    tidy "$old_share"
}

case "${1:-}" in
    "") do_install ;;
    --uninstall) do_uninstall ;;
    -h | --help) sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' ;;
    *) echo "usage: $0 [--uninstall]" >&2; exit 2 ;;
esac
