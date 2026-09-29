#!/usr/bin/env bash
# Builds an unsigned, reproducible tabdock-<version>.xpi from extension/, containing
# exactly the files the manifest references. Sign it with packaging/sign-extension.sh.
#
#   packaging/build-extension.sh              -> web-ext-artifacts/tabdock-<version>.xpi
#   OUT_DIR=/some/dir packaging/build-extension.sh
set -euo pipefail

root="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
out_dir="${OUT_DIR:-$root/web-ext-artifacts}"

python3 - "$root/extension" "$out_dir" <<'PY'
import json
import os
import sys
import zipfile

src, out_dir = sys.argv[1:3]
with open(os.path.join(src, "manifest.json")) as f:
    manifest = json.load(f)
files = ["manifest.json", *manifest["background"]["scripts"], *manifest["icons"].values()]
page = manifest["options_ui"]["page"]
files += [page, page.replace(".html", ".js")]

os.makedirs(out_dir, exist_ok=True)
out = os.path.join(out_dir, f"tabdock-{manifest['version']}.xpi")
with zipfile.ZipFile(out, "w") as z:
    for name in files:
        # fixed timestamp and mode: the same sources always give the same bytes
        info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        with open(os.path.join(src, name), "rb") as f:
            z.writestr(info, f.read())
print(f"built {out}")
PY
