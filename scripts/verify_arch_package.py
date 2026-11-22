"""Check the dependency-free Arch payload against the selected source tree."""

import argparse
import hashlib
from pathlib import Path
import tarfile


def verify(package: Path, source: Path) -> None:
    root = "usr/lib/localmind"
    payload = {
        f"{root}/{path.relative_to(source).as_posix()}": path
        for folder in ("config", "static")
        for path in (source / folder).rglob("*")
        if path.is_file()
    }
    payload.update({
        f"{root}/localmind/{path.name}": path
        for path in (source / "localmind").glob("*.py")
    })
    for name in ("start.py", "requirements.txt", "requirements-voice.txt"):
        payload[f"{root}/{name}"] = source / name
    payload.update({
        "usr/bin/localmind": source / "installer/linux/localmind",
        "usr/share/applications/localmind.desktop": source / "installer/linux/localmind.desktop",
        "usr/share/icons/hicolor/256x256/apps/localmind.png": source / "static/assets/localmind.png",
        "usr/share/licenses/localmind/LICENSE": source / "LICENSE",
    })
    metadata = {".PKGINFO", ".BUILDINFO", ".MTREE"}
    seen = set()
    with tarfile.open(package, "r:zst") as archive:
        for member in archive:
            name = member.name
            parts = Path(name).parts
            if not parts or Path(name).is_absolute() or ".." in parts:
                raise ValueError(f"Unsafe archive path: {name}")
            if member.isdir() and any(path.startswith(name + "/") for path in payload):
                continue
            if not member.isfile() or name in seen or name not in payload.keys() | metadata:
                raise ValueError(f"Unexpected package member: {name}")
            seen.add(name)
            with archive.extractfile(member) as entry:
                if name == ".BUILDINFO":
                    fields = entry.read().decode().splitlines()
                    if not {"builddir = /tmp/localmind-build", "startdir = /tmp/localmind-source"}.issubset(fields):
                        raise ValueError("Expected anonymous build and source directories in .BUILDINFO")
                if name in payload and hashlib.file_digest(entry, "sha256").digest() != hashlib.sha256(
                    payload[name].read_bytes()
                ).digest():
                    raise ValueError(f"Source mismatch: {name}")
    missing = (payload.keys() | metadata) - seen
    if missing:
        raise ValueError(f"Missing package members: {sorted(missing)}")
    print(f"Verified {len(payload)} package files against source")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--source", type=Path, default=Path.cwd())
    args = parser.parse_args()
    verify(args.package, args.source)
