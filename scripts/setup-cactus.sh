#!/usr/bin/env bash
# Install pinned CPU Cactus artifacts. Does not edit config or restart services.
set -euo pipefail
DEST="${AGAVAI_CACTUS_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/agavai/cactus}"
python3 -m venv "$DEST/venv"
"$DEST/venv/bin/python" -m pip install 'cactus-needle==3.2.8'
"$DEST/venv/bin/python" - "$DEST" <<'PY'
import hashlib
import io
import json
from pathlib import Path
import platform
import sys
import urllib.request
import zipfile

root = Path(sys.argv[1]).resolve()
if platform.system() != "Linux" or platform.libc_ver()[0] != "glibc":
    sys.exit("This installer supports Omarchy Linux with glibc.")
arches = {"x86_64": "b909897e11cf4da9566df6370f8a63564693fbd6edeaac0b8678b71865d4dc24",
          "aarch64": "cda9aa23eec3cc2cc6fea43ae5ba32b9d39a1487a198d8e2d86c1314dfe04873"}
arch = platform.machine()
if arch not in arches:
    sys.exit(f"Unsupported Cactus architecture: {arch}")
revision = "d6c7d6a2e9655505e0f8e23339356dd1705900eb"

def fetch(repo, revision, name, sha):
    with urllib.request.urlopen(f"https://huggingface.co/{repo}/resolve/{revision}/{name}", timeout=120) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != sha:
        sys.exit(f"SHA256 mismatch: {name}")
    return data

wheel = f"python/cactus_needle-3.3.3-py3-none-manylinux2014_{arch}.whl"
archive = zipfile.ZipFile(io.BytesIO(fetch("Cactus-Compute/needle3", revision, wheel, arches[arch])))
library = root / "libneedle.so"
partial_library = library.with_suffix(".partial")
partial_library.write_bytes(archive.read("needle/libneedle3.so"))
partial_library.replace(library)
artifacts = [
    ("Cactus-Compute/needle3", revision, "needle3.cact", "c9d915eca282ed42d1a09b143b592adb4cc6744ffe2d294adf5cfc5548170c38"),
    ("Cactus-Compute/whistle", "741118687e1f008f06d1351a402a731274789790", "whistle.cact", "b6e02f048568ac5d01a2042556c658061e699acbc0aa2a1439f52f3d461dffeb"),
]
for repo, revision, filename, sha in artifacts:
    path = root / filename
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        data = fetch(repo, revision, filename, sha)
        partial = path.with_suffix(".partial")
        partial.write_bytes(data)
        partial.replace(path)
(root / "manifest.json").write_text(json.dumps({"python_package":"cactus-needle==3.2.8", "native_engine":"3.3.3", "arch":arch,
                                               "sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [library, root/'needle3.cact', root/'whistle.cact']}}, indent=2)+'\n')
print(f"Installed CPU Cactus artifacts in {root}")
print(f"Set venv = {str(root/'venv')!r}, runtime_library = {str(library)!r}, and the corresponding model_path in config.")
PY
