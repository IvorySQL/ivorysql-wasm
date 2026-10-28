"""Run the complete public CLI against real directories and tar archives.

Set IVORYSQL_WASM_SOURCE_ROOT to run these same tests against another tree.
Directory CLI coverage requires a host where tarfile.open(directory) raises
IsADirectoryError, as required by the unchanged upstream directory dispatch.
"""

import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

SOURCE_ROOT = Path(
    os.environ.get("IVORYSQL_WASM_SOURCE_ROOT", str(Path(__file__).resolve().parents[1]))
)
SCRIPT = SOURCE_ROOT / "packages/buildroot/tools/fs2json.py"
DIRECTORIES = ("cache", "cache/nested", "cache-old", "etc", "var", "var/log")
FILES = {
    "cache/secret.txt": b"excluded cache\n",
    "cache/nested/secret.txt": b"excluded descendant\n",
    "cache-old/keep.txt": b"keep prefix sibling\n",
    "etc/config": b"keep configuration\n",
    "var/log/app.log": b"exclude separately\n",
}


def flatten(nodes, prefix=""):
    result = {}
    for node in nodes:
        path = prefix + node[0]
        result[path] = node
        if stat.S_ISDIR(node[3]):
            result.update(flatten(node[6], path + "/"))
    return result


class Fs2jsonExclusionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="fs2json-excludes-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / "input"
        self.directory.mkdir()
        for name in DIRECTORIES:
            (self.directory / name).mkdir()
        for name, data in FILES.items():
            (self.directory / name).write_bytes(data)
        self.archive = self.root / "input.tar"
        with tarfile.open(self.archive, "w") as archive:
            for name in DIRECTORIES:
                member = self.member(name, 0o755)
                member.type = tarfile.DIRTYPE
                archive.addfile(member)
            for name, data in FILES.items():
                member = self.member(name, 0o644)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
            member = self.member("etc/config-link", 0o777)
            member.type = tarfile.SYMTYPE
            member.linkname = "config"
            archive.addfile(member)

    @staticmethod
    def member(name, mode):
        member = tarfile.TarInfo(name)
        member.mode = mode
        member.uid = 1000
        member.gid = 1000
        member.mtime = 1700000000
        return member

    def run_cli(self, source, *excludes):
        output = self.root / "output.json"
        command = [sys.executable, str(SCRIPT), "--out", str(output)]
        for exclude in excludes:
            command.extend(["--exclude", exclude])
        command.append(str(source))
        completed = subprocess.run(
            command, cwd=self.root, capture_output=True, text=True, timeout=30
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        return json.loads(output.read_text())

    def assert_retained_file(self, nodes, name):
        node = nodes[name]
        self.assertTrue(stat.S_ISREG(node[3]))
        self.assertEqual(node[1], len(FILES[name]))
        self.assertEqual(node[6], hashlib.sha256(FILES[name]).hexdigest()[:8] + ".bin")

    def test_tar_excludes_directory_and_descendants_but_not_prefix_sibling(self):
        result = self.run_cli(self.archive, "cache")
        nodes = flatten(result["fsroot"])
        self.assertNotIn("cache", nodes)
        self.assertFalse(any(name.startswith("cache/") for name in nodes))
        self.assert_retained_file(nodes, "cache-old/keep.txt")
        self.assert_retained_file(nodes, "etc/config")
        self.assertEqual(
            result["size"],
            sum(len(data) for name, data in FILES.items() if not name.startswith("cache/")),
        )

    def test_tar_repeated_normalized_excludes(self):
        result = self.run_cli(self.archive, "/cache/", "./var/log")
        nodes = flatten(result["fsroot"])
        self.assertNotIn("cache", nodes)
        self.assertNotIn("var/log", nodes)
        self.assertIn("var", nodes)
        self.assertEqual(nodes["var"][6], [])
        self.assert_retained_file(nodes, "cache-old/keep.txt")
        self.assertEqual(
            result["size"], len(FILES["cache-old/keep.txt"]) + len(FILES["etc/config"])
        )

    def test_tar_default_preserves_layout_metadata_hashes_and_symlink(self):
        result = self.run_cli(self.archive)
        nodes = flatten(result["fsroot"])
        self.assertEqual(result["version"], 3)
        self.assertEqual(set(nodes), set(DIRECTORIES) | set(FILES) | {"etc/config-link"})
        self.assertEqual(result["size"], sum(map(len, FILES.values())))
        for name in FILES:
            self.assert_retained_file(nodes, name)
            self.assertEqual(nodes[name][2:3], [1700000000])
            self.assertEqual(nodes[name][4:6], [1000, 1000])
        self.assertTrue(stat.S_ISLNK(nodes["etc/config-link"][3]))
        self.assertEqual(nodes["etc/config-link"][6], "config")

    def test_tar_nonmatching_exclude_is_identical_to_default(self):
        self.assertEqual(self.run_cli(self.archive, "absent"), self.run_cli(self.archive))

    @unittest.skipIf(os.name == "nt", "unchanged directory CLI dispatch requires IsADirectoryError")
    def test_directory_excludes_still_prune_subtrees(self):
        result = self.run_cli(self.directory, "cache", "var/log")
        nodes = flatten(result["fsroot"])
        self.assertNotIn("cache", nodes)
        self.assertNotIn("var/log", nodes)
        self.assert_retained_file(nodes, "cache-old/keep.txt")
        self.assert_retained_file(nodes, "etc/config")

    @unittest.skipIf(os.name == "nt", "unchanged directory CLI dispatch requires IsADirectoryError")
    def test_directory_default_still_includes_all_files(self):
        nodes = flatten(self.run_cli(self.directory)["fsroot"])
        self.assertEqual(set(nodes), set(DIRECTORIES) | set(FILES))
        for name in FILES:
            self.assert_retained_file(nodes, name)


if __name__ == "__main__":
    unittest.main()
