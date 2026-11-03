"""Authored archives only: no game files and no official compiler required."""
import copy
import io
import json
from pathlib import Path
import stat
import struct
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

import reuse_release_compiler as reuse


def elf():
    interpreter = b"/system/bin/linker64\0"
    data = bytearray(120) + interpreter
    data[:7] = b"\x7fELF\x02\x01\x01"
    struct.pack_into("<HHI", data, 16, 3, 183, 1)
    struct.pack_into("<Q", data, 32, 64)
    struct.pack_into("<HH", data, 54, 56, 1)
    struct.pack_into("<I", data, 64, 3)
    struct.pack_into("<Q", data, 72, 120)
    struct.pack_into("<Q", data, 96, len(interpreter))
    return bytes(data)


def bundle(entries):
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as archive:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            for name, data in entries:
                # Passing a ZipInfo avoids Windows normalizing a deliberately
                # unsafe backslash name before this fixture reaches the reader.
                if isinstance(name, str):
                    entry = zipfile.ZipInfo()
                    entry.filename = name
                else:
                    entry = name
                archive.writestr(entry, data)
    return result.getvalue()


class ReuseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.apk, self.output = self.root / "official.apk", self.root / "output"
        source_dir = self.root / "tools/android"
        source_dir.mkdir(parents=True)
        for name in reuse.SOURCE_SHA256:
            source_dir.joinpath(name).write_bytes(Path(reuse.__file__).with_name(name).read_bytes())
        self.metadata = copy.deepcopy(reuse.METADATA)
        self.drivers = {name: elf() for name in self.metadata["sha256"]}
        self.data_files = [("licenses/" + name, b"authored license fixture\n")
                           for name in ("LLVM.txt", "NDK-toolchain.txt", "NDK.txt")]
        self.data_files += [("lib/clang/20/include/fixture.h", b"/* authored header */\n"),
                            ("sysroot/usr/include/fixture.h", b"/* authored header */\n")]
        self.build = {"abi": "arm64-v8a", "api": 33,
                      "llvm_revision": self.metadata["llvm_revision"], "ndk_revision": reuse.NDK_REVISION}

    def seal(self, inner_extra=(), outer_extra=(), metadata_change=None, corrupt_driver=False):
        self.metadata["sha256"] = {name: reuse.digest(data) for name, data in self.drivers.items()}
        self.build["sha256"] = {name: reuse.digest(data) for name, data in self.data_files}
        self.build["sha256"].update({"bin/" + key: self.metadata["sha256"][value]
                                    for key, value in self.metadata["executables"].items()})
        build_raw = json.dumps(self.build).encode()
        self.metadata["compiler_identity"] = reuse.digest(build_raw)
        data = bundle(self.data_files + [("build.json", build_raw)] + list(inner_extra))
        self.metadata["data_sha256"] = reuse.digest(data)
        on_disk = copy.deepcopy(self.metadata)
        if metadata_change:
            on_disk.update(metadata_change)
        entries = [("assets/toolchain-apk.json", json.dumps(on_disk).encode()),
                   ("assets/toolchain-data.zip", data)]
        entries += [("lib/arm64-v8a/" + name, b"changed" if corrupt_driver else data)
                    for name, data in self.drivers.items()]
        # These unrelated components must never be reused.
        entries += [("assets/runtime-sdk.json", b"old sdk"),
                    ("assets/python-source.zip", b"old python"),
                    ("assets/extractor-apk.json", b"old extractor"),
                    ("lib/arm64-v8a/libmain.so", b"placeholder outside compiler")]
        self.apk.write_bytes(bundle(entries + list(outer_extra)))
        self.addCleanup(patch.stopall)
        patch.object(reuse, "APK_SHA256", reuse.digest(self.apk.read_bytes())).start()
        patch.object(reuse, "METADATA", copy.deepcopy(self.metadata)).start()

    def run_reuse(self):
        return reuse.reuse(self.apk, self.output, self.root)

    def test_roundtrip_copies_only_compiler_and_preserves_licenses(self):
        self.seal()
        result = self.run_reuse()
        names = {p.relative_to(self.output).as_posix() for p in self.output.rglob("*") if p.is_file()}
        self.assertEqual(names, {"assets/toolchain-apk.json", "assets/toolchain-data.zip"} |
                         {"jniLibs/arm64-v8a/" + name for name in self.drivers})
        for name, data in self.drivers.items():
            self.assertEqual((self.output / "jniLibs/arm64-v8a" / name).read_bytes(), data)
        with zipfile.ZipFile(self.output / "assets/toolchain-data.zip") as archive:
            self.assertEqual(archive.read("licenses/LLVM.txt"), b"authored license fixture\n")
        self.assertEqual(result["compiler"], self.metadata)

    def test_rejects_wrong_apk_pin(self):
        self.seal()
        with patch.object(reuse, "APK_SHA256", "0" * 64):
            with self.assertRaisesRegex(ValueError, "APK checksum"):
                self.run_reuse()
        self.assertFalse(self.output.exists())

    def test_normalizes_source_line_endings_and_rejects_source_changes(self):
        self.seal()
        path = self.root / "tools/android/build_toolchain.py"
        path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        reuse.verify_sources(self.root)
        path.write_bytes(path.read_bytes() + b"# changed\n")
        with self.assertRaisesRegex(ValueError, "source pin"):
            self.run_reuse()

    def test_rejects_metadata_abi_api_revision_identity_and_hashes(self):
        self.seal()
        for key, value in (("abi", "x86_64"), ("api", 34), ("llvm_revision", "other"),
                           ("compiler_identity", "0" * 64), ("data_sha256", "0" * 64)):
            with self.subTest(key=key), patch.dict(reuse.METADATA, {key: value}):
                with self.assertRaisesRegex(ValueError, "metadata mismatch"):
                    self.run_reuse()
        self.assertFalse(self.output.exists())

    def test_rejects_other_ndk_revision_inside_data(self):
        self.build["ndk_revision"] = "unreviewed"
        self.seal()
        with self.assertRaisesRegex(ValueError, "revision mismatch"):
            self.run_reuse()

    def test_rejects_changed_driver_even_when_apk_pin_matches(self):
        self.seal(corrupt_driver=True)
        with self.assertRaisesRegex(ValueError, "driver checksum"):
            self.run_reuse()
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob("compiler-reuse-*")))

    def test_rejects_wrong_data_pin_and_identity(self):
        self.seal()
        with zipfile.ZipFile(self.apk) as archive:
            data = archive.read("assets/toolchain-data.zip")
        with self.assertRaisesRegex(ValueError, "data checksum"):
            reuse.verify_data(data + b"changed", self.metadata)
        metadata = {**self.metadata, "compiler_identity": "0" * 64}
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            reuse.verify_data(data, metadata)

    def test_rejects_invalid_elf_even_with_matching_hashes(self):
        self.drivers['libwwhd-clang-driver.so'] = b'authored non-ELF fixture'
        self.seal()
        with self.assertRaisesRegex(ValueError, "ELF64"):
            self.run_reuse()

    def test_rejects_changed_inner_member(self):
        self.seal()
        with zipfile.ZipFile(self.apk) as outer, zipfile.ZipFile(io.BytesIO(outer.read('assets/toolchain-data.zip'))) as inner:
            data = bundle([(name, b'changed' if name == 'licenses/LLVM.txt' else inner.read(name))
                           for name in inner.namelist()])
        metadata = {**self.metadata, 'data_sha256': reuse.digest(data)}
        with self.assertRaisesRegex(ValueError, "member checksum mismatch"):
            reuse.verify_data(data, metadata)

    def test_rejects_unsafe_outer_and_inner_paths(self):
        for name in ("../escape", "/absolute", "C:/drive", "back\\slash", "a//b", "a/./b", "line\nbreak"):
            for layer in ("outer", "inner"):
                with self.subTest(name=name, layer=layer):
                    self.seal(**{layer + "_extra": [(name, b"authored fixture")]})
                    with self.assertRaisesRegex(ValueError, "unsafe ZIP"):
                        self.run_reuse()
                    self.assertFalse(self.output.exists())

    def test_rejects_duplicate_members(self):
        for layer, name in (("outer", "assets/toolchain-apk.json"), ("inner", "licenses/LLVM.txt")):
            with self.subTest(layer=layer):
                self.seal(**{layer + "_extra": [(name, b"duplicate")]})
                with self.assertRaisesRegex(ValueError, "duplicate ZIP"):
                    self.run_reuse()

    def test_rejects_symlinks_and_limits(self):
        link = zipfile.ZipInfo("licenses/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.seal(inner_extra=[(link, b"../target")])
        with self.assertRaisesRegex(ValueError, "links/special"):
            self.run_reuse()
        self.seal()
        for setting in ("MAX_MEMBERS", "MAX_FILE", "MAX_TOTAL"):
            with self.subTest(setting=setting), patch.object(reuse, setting, 1):
                with self.assertRaisesRegex(ValueError, "limit"):
                    self.run_reuse()

    def test_rejects_extra_data_and_missing_licenses(self):
        self.seal(inner_extra=[("sysroot/extra.txt", b"extra")])
        with self.assertRaisesRegex(ValueError, "inventory mismatch"):
            self.run_reuse()
        self.data_files = [(n, b) for n, b in self.data_files if n != "licenses/LLVM.txt"]
        self.seal()
        with self.assertRaisesRegex(ValueError, "missing compiler license"):
            self.run_reuse()

    def test_refuses_existing_output(self):
        self.seal()
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError, "fresh compiler output"):
            self.run_reuse()

    def test_rejects_duplicate_json_keys(self):
        with self.assertRaisesRegex(ValueError, "duplicate JSON"):
            reuse.unique_json(b'{"abi":"arm64-v8a","abi":"x86_64"}')


if __name__ == "__main__":
    unittest.main()
