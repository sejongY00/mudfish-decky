"""Build the installable Decky zip: <out>/mudfish-decky-<version>.zip with a top-level mudfish-decky/ folder.

Usage: python scripts/package.py [OUT_DIR]   (run from the repository root after `pnpm build`)
"""
import json
import os
import sys
import zipfile

PLUGIN_DIR = "mudfish-decky"
INCLUDE = ["plugin.json", "package.json", "main.py", "README.md", "LICENSE", "dist", "py_modules"]
REQUIRED = ["plugin.json", "package.json", "main.py", os.path.join("dist", "index.js")]


def read_version(src: str) -> str:
    with open(os.path.join(src, "package.json")) as f:
        return json.load(f)["version"]


def _files(src: str):
    for entry in INCLUDE:
        path = os.path.join(src, entry)
        if os.path.isfile(path):
            yield entry
        elif os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                dirs[:] = sorted(d for d in dirs if d != "__pycache__")
                for name in sorted(files):
                    # bytecode is rebuilt on the Deck; source maps are only for debugging
                    if not name.endswith((".pyc", ".map")):
                        yield os.path.relpath(os.path.join(root, name), src)


def build_zip(src: str, out_dir: str) -> str:
    missing = [p for p in REQUIRED if not os.path.isfile(os.path.join(src, p))]
    if missing:
        sys.exit(f"package: missing {', '.join(missing)} (run the build first)")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{PLUGIN_DIR}-{read_version(src)}.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in _files(src):
            z.write(os.path.join(src, rel), f"{PLUGIN_DIR}/{rel.replace(os.sep, '/')}")
    return out


if __name__ == "__main__":
    print(build_zip(".", sys.argv[1] if len(sys.argv) > 1 else "out"))
