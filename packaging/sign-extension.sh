#!/usr/bin/env bash
# Signs the extension with your addons.mozilla.org API credentials (unlisted: private, automatic).
#
#   packaging/sign-extension.sh              ask for the credentials, lint, sign, verify the result
#   packaging/sign-extension.sh --save       ...and remember them in a private file after it worked
#   packaging/sign-extension.sh --forget     delete the remembered credentials
#   packaging/sign-extension.sh --dry-run    check everything except contacting Mozilla
#
# The credentials are two values from https://addons.mozilla.org/developers/addon/api/key/ :
#   JWT issuer  looks like  user:12345678:123        (copy all of it, including "user:")
#   JWT secret  64 characters                        (hidden while you paste it)
# They are asked one at a time, checked before anything is sent, and passed to web-ext through
# this script's environment only: never on a command line, in your shell history or in the repo.
# What you typed is never printed back, only its shape. --save keeps the pair, once signing has
# proven it right, in ~/.config/tabdock/amo-credentials (mode 600, outside the repo).
set -euo pipefail

root="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
artifacts="${ARTIFACTS_DIR:-$root/web-ext-artifacts}"
creds_dir="${XDG_CONFIG_HOME:-$HOME/.config}/tabdock"
creds_file="$creds_dir/amo-credentials"
# saved before the rename to tabdock: still used, and deleted by --forget, while there is no new one
legacy_creds="${XDG_CONFIG_HOME:-$HOME/.config}/openbox-sidepanel/amo-credentials"
[[ -e $creds_file || ! -e $legacy_creds ]] || creds_file=$legacy_creds

save=0 forget=0 dry=0
for arg in "$@"; do
    case $arg in
        --save) save=1 ;;
        --forget) forget=1 ;;
        --dry-run) dry=1 ;;
        -h | --help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) echo "usage: $0 [--save | --forget | --dry-run]" >&2; exit 2 ;;
    esac
done

die() { echo "error: $*" >&2; exit 1; }
bad() { echo "error: $*" >&2; exit 2; }  # something about what you typed, not about the machine

if (( forget )); then
    if [[ -e $creds_file ]]; then rm -- "$creds_file"; echo "deleted $creds_file"; else echo "nothing saved at $creds_file"; fi
    exit 0
fi

# -- what is being signed ---------------------------------------------------------------------
version="$(<"$root/VERSION")"
manifest_version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$root/extension/manifest.json")"
[[ $version == "$manifest_version" ]] || die "VERSION ($version) and extension/manifest.json ($manifest_version) differ; fix that first"

is_signed() {  # a file is signed when Mozilla's signature is inside it: the name proves nothing
    python3 - "$1" <<'PY'
import sys
import zipfile

try:
    sys.exit(0 if "META-INF/mozilla.rsa" in zipfile.ZipFile(sys.argv[1]).namelist() else 1)
except (OSError, zipfile.BadZipFile):
    sys.exit(1)
PY
}

newest_signed() {  # the newest signed file for this version (web-ext names it <id>-<version>.xpi), if any
    local f best="" best_time=0 t
    for f in "$artifacts"/*"$version".xpi; do
        [[ -e $f ]] && is_signed "$f" || continue
        t="$(stat -c %Y "$f")"
        if (( t >= best_time )); then best="$f"; best_time=$t; fi
    done
    printf '%s' "$best"
}
# The name the GitHub release attaches the signed file by, which packaging/PKGBUILD downloads it by.
release_file="$artifacts/tabdock-$version.xpi"

for_release() {  # a copy of the signed file under that name, and what to do with it
    [[ $1 -ef $release_file ]] || cp -- "$1" "$release_file"
    echo
    echo "for the release: $release_file"
    echo "  attach it to the GitHub release v$version, for example:"
    echo "    gh release upload v$version $(printf '%q' "$release_file")"
    echo "  packaging/PKGBUILD downloads it from there (to build the package before uploading, copy it into packaging/)"
}

existing="$(newest_signed)"
if [[ -n $existing ]]; then
    echo "version $version is already signed: $existing"
    echo "Mozilla rejects a version number it has already signed: to sign again, raise VERSION and"
    echo "extension/manifest.json first (they must match)."
    for_release "$existing"
    exit 0
fi

# -- credentials ----------------------------------------------------------------------------------
clean() {  # strip carriage returns, surrounding whitespace and one pair of surrounding quotes
    local v=${1//$'\r'/}
    v="${v#"${v%%[![:space:]]*}"}"
    v="${v%"${v##*[![:space:]]}"}"
    if [[ $v == \'*\' || $v == \"*\" ]]; then v=${v:1:${#v}-2}; fi
    printf '%s' "$v"
}

ask() {  # ask PROMPT HIDDEN: a terminal gets a prompt (hidden for the secret), a pipe is read as lines
    local prompt=$1 hidden=$2 value=
    if [[ -t 0 ]]; then
        if (( hidden )); then
            read -rsp "$prompt" value
            echo >&2
        else
            read -rp "$prompt" value
        fi
    else
        IFS= read -r value || true
    fi
    clean "$value"
}

from_file=0
if [[ -f $creds_file ]]; then
    mode="$(stat -c %a "$creds_file")"
    [[ $mode == 600 ]] || die "$creds_file is readable by others (mode $mode); run: chmod 600 $creds_file"
    { IFS= read -r issuer; IFS= read -r secret; } < "$creds_file" || true
    issuer="$(clean "$issuer")"
    secret="$(clean "$secret")"
    from_file=1
    echo "using the credentials saved in $creds_file (packaging/sign-extension.sh --forget deletes them)"
else
    echo "Credentials from https://addons.mozilla.org/developers/addon/api/key/"
    issuer="$(ask 'JWT issuer (looks like user:12345678:123): ' 0)"
    secret="$(ask 'JWT secret (64 characters, hidden): ' 1)"
fi

# What was typed is never echoed back, only described: a secret pasted at the wrong prompt must not
# end up in the error message.
where=""
if (( from_file )); then
    where="; these came from $creds_file, so run packaging/sign-extension.sh --forget and enter them again"
fi
if [[ ! $issuer =~ ^user:[0-9]+:[0-9]+$ ]]; then
    hint="what was entered has ${#issuer} characters"
    if [[ $issuer != user:* && ${#issuer} -eq 64 ]]; then
        hint="$hint and looks like the secret: are the two values swapped?"
    elif [[ $issuer != user:* ]]; then
        hint="$hint and does not start with user:"
    fi
    bad "the JWT issuer must look like user:12345678:123 (the word user: and both numbers); $hint$where"
fi
if [[ ${#secret} -ne 64 || $secret == *[[:space:]]* ]]; then
    hint="what was entered is ${#secret} characters long"
    if [[ $secret == user:* ]]; then hint="$hint and starts with user:, which is the issuer: are the two values swapped?"; fi
    bad "the JWT secret should be 64 characters without spaces; $hint$where"
fi
echo "credentials look right: issuer user:..., secret 64 characters"

if (( dry )); then
    echo "dry run: would lint and sign version $version as unlisted into $artifacts; nothing was sent"
    if (( save )); then echo "(--save stores the credentials only after a real signing has worked)"; fi
    exit 0
fi

# -- lint, sign, verify ---------------------------------------------------------------------------
command -v npx > /dev/null || die "npx not found (install nodejs and npm)"
echo "linting..."
(cd "$root" && npx --yes web-ext lint --source-dir extension)

echo "signing version $version (Mozilla checks it: a few minutes)..."
export WEB_EXT_API_KEY="$issuer" WEB_EXT_API_SECRET="$secret"
(cd "$root" && npx --yes web-ext sign --source-dir extension --channel=unlisted --artifacts-dir "$artifacts")
unset WEB_EXT_API_KEY WEB_EXT_API_SECRET

signed="$(newest_signed)"
[[ -n $signed ]] || die "signing finished but there is no signed file for $version in $artifacts"

if (( save && ! from_file )); then  # the pair just worked, so it is worth keeping
    (
        umask 077
        mkdir -p -- "$creds_dir"
        printf '%s\n%s\n' "$issuer" "$secret" > "$creds_file"
    )
    chmod 600 "$creds_file"
    echo "saved the credentials to $creds_file (mode 600)"
fi
echo
echo "signed and verified: $signed"
echo "Install it in each browser: about:addons -> gear -> Install Add-on From File..."
for_release "$signed"
