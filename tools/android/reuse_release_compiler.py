#!/usr/bin/env python3
"""Reuse only the pinned official v0.5.0 Android compiler, never its runtime.

The LLVM/NDK build and packaging sources must still match the reviewed source
pins (CRLF is normalized to LF). Changing those sources requires reviewing this
reuse decision. Licenses remain inside the unmodified toolchain-data.zip.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import zipfile

RELEASE_URL = "https://github.com/ZeldaWWHDRecomp/ZeldaWWHDRecomp/releases/download/v0.5.0/WindWakerHD-v0.5.0-android-arm64.apk"
APK_SHA256 = "6af660aac1c67e5d99bbc653b1c2b9f0e429a8513e0e9ca0c497b0c37177f791"
NDK_REVISION = "30.0.16248370"
SOURCE_SHA256 = {
    "build_toolchain.py": "129b7fa8ee82f7914ebcf8a83a70407845fc891304201c0b4d0fc5e5c0db5fbf",
    "package_toolchain.py": "8940a3ea46a4d383c96e54c09919b8e346ad59ee4a70a0507d991815b90b0021",
}
METADATA = {
    "abi": "arm64-v8a", "api": 33,
    "llvm_revision": "87f0227cb60147a26a1eeb4fb06e3b505e9c7261",  # llvmorg-20.1.8
    "compiler_identity": "20fc4dcee0e439513aabce08010c415dfd847c7e6f836d9a2e53f268f085844e",
    "executables": {"clang": "libwwhd-clang-driver.so", "ld.lld": "libwwhd-ld.lld-driver.so",
                    "llvm-ar": "libwwhd-ar-driver.so"},
    "sha256": {
        "libwwhd-clang-driver.so": "5f6069f232a27b86085273a7a79615633acb362967d7a96109f35b4021b70e97",
        "libwwhd-ld.lld-driver.so": "313e89fb21d63585d708aef83512c9a8c260abf98903ca90acc6526dff39c58f",
        "libwwhd-ar-driver.so": "2303699d1160c0cb31a5785ffc70bedbd6cbf2362442e626f911f264517c4738",
    },
    "data_sha256": "dd6977defd9c743d38f0fef54fd600270d6b7fc6dad978aedb1beb814d6133c4",
}
MAX_MEMBERS = 20000
MAX_FILE = 512 * 1024 * 1024
MAX_TOTAL = 1024 * 1024 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unique_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=pairs)


def inventory(archive):
    """Reject ambiguous names, links and oversized ZIPs before reading members."""
    entries = archive.infolist()
    if len(entries) > MAX_MEMBERS or sum(i.file_size for i in entries) > MAX_TOTAL:
        raise ValueError("ZIP exceeds inventory limits")
    seen = set()
    for item in entries:
        # ZipInfo normalizes backslashes on Windows and truncates at NUL.
        name = item.orig_filename
        parts = name.rstrip("/").split("/")
        if (not name or name != item.filename or "\\" in name or ":" in name
                or any(ord(char) < 32 or ord(char) == 127 for char in name)
                or any(p in ("", ".", "..") for p in parts)
                or PurePosixPath(name).is_absolute()):
            raise ValueError("unsafe ZIP path: " + name)
        # APK resources and Linux UAPI headers have legitimate case-distinct
        # names. This archive remains zipped; only fixed driver names are saved.
        key = name.rstrip("/")
        if key in seen:
            raise ValueError("duplicate ZIP path: " + name)
        seen.add(key)
        kind = stat.S_IFMT(item.external_attr >> 16)
        if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or item.flag_bits & 1:
            raise ValueError("ZIP links/special files/encryption are forbidden")
        if item.file_size > MAX_FILE:
            raise ValueError("ZIP member exceeds size limit")
    files = {i.filename for i in entries if not i.is_dir()}
    for name in files:
        if any(str(parent) in files for parent in PurePosixPath(name).parents if str(parent) != "."):
            raise ValueError("ZIP file/directory conflict")
    return files


def verify_sources(root):
    for name, expected in SOURCE_SHA256.items():
        path = root / "tools/android" / name
        if path.is_symlink() or digest(path.read_bytes().replace(b"\r\n", b"\n")) != expected:
            raise ValueError("compiler source pin mismatch: " + name)


def verify_data(data, metadata):
    if digest(data) != metadata["data_sha256"]:
        raise ValueError("compiler data checksum mismatch")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        files = inventory(archive)
        build_raw = archive.read("build.json")
        if digest(build_raw) != metadata["compiler_identity"]:
            raise ValueError("compiler identity mismatch")
        build = unique_json(build_raw)
        if any(build.get(key) != metadata[key] for key in ("abi", "api", "llvm_revision")) or build.get("ndk_revision") != NDK_REVISION:
            raise ValueError("compiler build ABI/API/LLVM/NDK revision mismatch")
        hashes = build.get("sha256", {})
        drivers = {"bin/" + key: metadata["sha256"][value] for key, value in metadata["executables"].items()}
        if not isinstance(hashes, dict) or {k: hashes.get(k) for k in drivers} != drivers:
            raise ValueError("compiler driver inventory mismatch")
        if files != (set(hashes) - set(drivers)) | {"build.json"}:
            raise ValueError("compiler data inventory mismatch")
        for name in files - {"build.json"}:
            if not name.startswith(("licenses/", "lib/clang/20/", "sysroot/")):
                raise ValueError("unexpected compiler data path: " + name)
            with archive.open(name) as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != hashes[name]:
                    raise ValueError("compiler data member checksum mismatch: " + name)
        for license_name in ("LLVM.txt", "NDK-toolchain.txt", "NDK.txt"):
            if "licenses/" + license_name not in files:
                raise ValueError("missing compiler license: " + license_name)


def reuse(apk, output, source_root=None):
    apk, output = Path(apk).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("use a fresh compiler output directory")
    verify_sources(Path(source_root) if source_root else Path(__file__).resolve().parents[2])
    with apk.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != APK_SHA256:
            raise ValueError("official APK checksum mismatch")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="compiler-reuse-", dir=output.parent))
    try:
        with zipfile.ZipFile(apk) as archive:
            inventory(archive)
            raw = archive.read("assets/toolchain-apk.json")
            metadata = unique_json(raw)
            if metadata != METADATA:
                raise ValueError("pinned compiler metadata mismatch (ABI/API/revision/identity/checksums)")
            data = archive.read("assets/toolchain-data.zip")
            verify_data(data, metadata)
            assets = temporary / "assets"
            native = temporary / "jniLibs" / metadata["abi"]
            assets.mkdir()
            native.mkdir(parents=True)
            (assets / "toolchain-apk.json").write_bytes(raw)
            (assets / "toolchain-data.zip").write_bytes(data)
            # Source pins were checked before importing the current ELF validator.
            from package_toolchain import validate_executable
            for name, expected in metadata["sha256"].items():
                driver = archive.read("lib/" + metadata["abi"] + "/" + name)
                if digest(driver) != expected:
                    raise ValueError("compiler driver checksum mismatch: " + name)
                target = native / name
                target.write_bytes(driver)
                validate_executable(target, 183)
                target.chmod(0o755)
        temporary.rename(output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {"source_url": RELEASE_URL, "apk_sha256": APK_SHA256,
            "compiler": metadata, "normalized_source_sha256": SOURCE_SHA256}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(reuse(args.apk, args.out), indent=2))


if __name__ == "__main__":
    main()
