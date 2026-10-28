"""Exercise the complete sync script with genuine generated filesystem metadata.

Main alone runs this test with existing real tools and an owned private WorkRoot.
Payloads represent the Buildroot kernel layout; they are not bootable kernels.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


def bash_path(path):
    path = Path(path).resolve()
    text = path.as_posix()
    if os.name == "nt" and path.drive:
        return "/" + path.drive[0].lower() + text[2:]
    return text


def snapshot(path):
    return {
        item.relative_to(path).as_posix(): item.read_bytes()
        for item in path.rglob("*")
        if item.is_file()
    }


class KernelSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(os.environ["WASM_SOURCE_ROOT"]).resolve(strict=True)
        cls.bash = Path(os.environ["WASM_BASH"]).resolve(strict=True)
        cls.utilities = Path(os.environ["WASM_UTILITY_BIN"]).resolve(strict=True)
        cls.jq = Path(os.environ["WASM_JQ"]).resolve(strict=True)
        cls.private = Path(os.environ["WASM_WORK_ROOT"]).resolve(strict=True)
        if not cls.private.is_dir() or cls.private == Path(cls.private.anchor):
            raise RuntimeError("Main must supply an owned, non-root private WorkRoot")
        if not cls.bash.is_file() or not cls.jq.is_file():
            raise RuntimeError("Existing real Bash and jq executables are required")
        if cls.jq.name not in ("jq", "jq.exe"):
            raise RuntimeError("WASM_JQ must be the actual jq CLI on PATH")
        for command in ("dirname", "cp", "rm", "grep", "sed"):
            if not any(
                (cls.utilities / name).is_file() for name in (command, command + ".exe")
            ):
                raise RuntimeError("Missing real utility: " + command)
        for relative in (
            "packages/runtime/scripts/sync-fs.sh",
            "packages/runtime/index.html",
            "packages/buildroot/tools/fs2json.py",
            "packages/buildroot/tools/copy-to-sha256.py",
        ):
            if not (cls.source / relative).is_file():
                raise RuntimeError("Missing complete upstream file: " + relative)

    def command(self, args, cwd, env=None):
        return (
            subprocess.run(  # noqa: UP022 - keep explicit, separately inspected pipes
                args,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
        )

    def check_layout(self, install_target, alternate_cwd):
        work = Path(tempfile.mkdtemp(prefix="wasm-kernel-", dir=self.private)).resolve()
        if work.parent != self.private or work.is_symlink():
            raise RuntimeError("Unexpected private fixture")
        try:
            runtime = work / "packages/runtime"
            scripts = runtime / "scripts"
            old_fs = runtime / "filesystem"
            generated = work / "packages/buildroot/build/filesystem"
            rootfs = work / "rootfs"
            unrelated = work / "unrelated cwd"
            for directory in (scripts, old_fs, generated, rootfs / "boot", unrelated):
                directory.mkdir(parents=True)
            source_script = self.source / "packages/runtime/scripts/sync-fs.sh"
            script = scripts / "sync-fs.sh"
            shutil.copyfile(source_script, script)
            index = runtime / "index.html"
            original_html = (self.source / "packages/runtime/index.html").read_bytes()
            self.assertEqual(original_html.count(b"./filesystem/e3c50838.bin"), 1)
            index.write_bytes(original_html)
            (old_fs / "old.bin").write_bytes(b"old-runtime")
            canary = work / "outside-runtime.bin"
            canary.write_bytes(b"outside-runtime\x00\xff")

            # Buildroot INSTALL_TARGET copies the same emitted image to /boot;
            # this project's post-image additionally moves it to rootfs/bzImage.
            payload = b"fixture-emitted-kernel\x00\xff\r\n"
            (rootfs / "bzImage").write_bytes(payload)
            if install_target:
                (rootfs / "boot/bzImage").write_bytes(payload)
            (rootfs / "boot/readme").write_bytes(b"ordinary boot directory entry")
            archive = work / "filesystem.tar"

            # Match post-image's tar -cf filesystem.tar rootfs/* layout, using
            # integral mtimes as the actual GNU tar build path does.
            def integral_mtime(member):
                member.mtime = 1788344684
                return member

            with tarfile.open(archive, "w", format=tarfile.GNU_FORMAT) as output:
                for item in sorted(rootfs.iterdir()):
                    output.add(
                        item, arcname="rootfs/" + item.name, filter=integral_mtime
                    )
            tools = self.source / "packages/buildroot/tools"
            for args in (
                [str(tools / "copy-to-sha256.py"), str(archive), str(generated)],
                [
                    str(tools / "fs2json.py"),
                    "--out",
                    str(generated / "filesystem.json"),
                    str(archive),
                ],
            ):
                result = self.command([sys.executable, *args], work)
                self.assertEqual(
                    result.returncode, 0, result.stderr.decode("utf-8", "replace")
                )
            metadata = json.loads((generated / "filesystem.json").read_text())
            kernel = next(row for row in metadata["fsroot"] if row[0] == "bzImage")
            expected_hash = hashlib.sha256(payload).hexdigest()[:8] + ".bin"
            self.assertEqual(kernel[6], expected_hash)
            boot = next(row for row in metadata["fsroot"] if row[0] == "boot")
            self.assertEqual(
                sum(row[0] == "bzImage" for row in boot[6]), int(install_target)
            )
            expected_files = snapshot(generated)

            # The complete production script performs rm only under this owned
            # fixture, never under the source checkout or another worker root.
            if (
                old_fs.resolve().parent != runtime.resolve()
                or not old_fs.resolve().is_relative_to(work)
            ):
                raise RuntimeError("Refusing removal outside private runtime")
            if (script.parent / "..").resolve() != runtime.resolve():
                raise RuntimeError("Unexpected script-derived runtime")
            env = dict(os.environ)
            for key in list(env):
                if key in (
                    "BASH_ENV",
                    "ENV",
                    "SHELLOPTS",
                    "BASHOPTS",
                ) or key.startswith("BASH_FUNC_"):
                    env.pop(key, None)
            env["PATH"] = os.pathsep.join((str(self.utilities), str(self.jq.parent)))
            result = self.command(
                [str(self.bash), "--noprofile", "--norc", bash_path(script)],
                unrelated if alternate_cwd else runtime,
                env,
            )
            diagnostic = result.stderr.decode("utf-8", "replace")
            self.assertEqual(result.returncode, 0, diagnostic)
            self.assertEqual(
                index.read_bytes(),
                original_html.replace(
                    b"./filesystem/e3c50838.bin",
                    ("./filesystem/" + expected_hash).encode("ascii"),
                ),
            )
            self.assertEqual(snapshot(old_fs), expected_files)
            self.assertEqual(snapshot(generated), expected_files)
            self.assertEqual(script.read_bytes(), source_script.read_bytes())
            self.assertEqual(canary.read_bytes(), b"outside-runtime\x00\xff")
        finally:
            if (
                work.is_symlink()
                or work.resolve().parent != self.private
                or not work.name.startswith("wasm-kernel-")
            ):
                raise RuntimeError("Refusing cleanup outside private WorkRoot")
            shutil.rmtree(work)

    def test_installed_kernel_from_runtime(self):
        self.check_layout(True, False)

    def test_installed_kernel_from_unrelated_cwd(self):
        self.check_layout(True, True)

    def test_default_layout_from_runtime(self):
        self.check_layout(False, False)

    def test_default_layout_from_unrelated_cwd(self):
        self.check_layout(False, True)


if __name__ == "__main__":
    unittest.main()
