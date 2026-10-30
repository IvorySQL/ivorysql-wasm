"""Main-only full sync-fs.sh regression with real Bash/cp/grep/sed/rm.

All mutations, including the production script's removal, occur in a new
validated child of Main's private WorkRoot. No commands are mocked.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


def bash_path(value):
    value = Path(value).resolve()
    text = value.as_posix()
    if os.name == 'nt' and value.drive:
        return '/' + value.drive[0].lower() + text[2:]
    return text


def snapshot(directory):
    if not directory.is_dir():
        return None
    return {
        'directories': sorted(item.relative_to(directory).as_posix()
                              for item in directory.rglob('*') if item.is_dir()),
        'files': {item.relative_to(directory).as_posix(): item.read_bytes()
                  for item in directory.rglob('*') if item.is_file()}
    }


class SyncSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (Path(os.environ['WASM_SOURCE_ROOT']).resolve(strict=True)
                      / 'packages/runtime/scripts/sync-fs.sh')
        cls.bash = Path(os.environ['WASM_BASH']).resolve(strict=True)
        cls.utility_bin = Path(os.environ['WASM_UTILITY_BIN']).resolve(strict=True)
        cls.private_root = Path(os.environ['WASM_WORK_ROOT']).resolve(strict=True)
        if not cls.source.is_file() or not cls.bash.is_file() or not cls.private_root.is_dir():
            raise RuntimeError('Main must supply the actual script, Bash and a private WorkRoot')
        if cls.private_root == Path(cls.private_root.anchor):
            raise RuntimeError('WorkRoot must not be a filesystem root')
        for command in ('cp', 'grep', 'sed', 'rm', 'dirname'):
            if not any((cls.utility_bin / name).is_file() for name in (command, command + '.exe')):
                raise RuntimeError('Existing real command required: ' + command)

    def run_sync(self, source_present, alternate_cwd):
        work = Path(tempfile.mkdtemp(prefix='wasm-sync-source-', dir=self.private_root)).resolve(strict=True)
        if work.parent != self.private_root or not work.name.startswith('wasm-sync-source-') or work.is_symlink():
            raise RuntimeError('Refusing unexpected private fixture root')
        try:
            runtime = work / 'packages/runtime'
            source_dir = work / 'packages/buildroot/build/filesystem'
            scripts = runtime / 'scripts'
            old_fs = runtime / 'filesystem'
            unrelated = work / 'unrelated cwd'
            for directory in (scripts, old_fs / 'nested/empty', source_dir.parent, unrelated):
                directory.mkdir(parents=True, exist_ok=True)
            script = scripts / 'sync-fs.sh'
            shutil.copyfile(self.source, script)  # complete original bytes; no algorithm extraction
            original_script = self.source.read_bytes()
            old_metadata = b'{"fsroot":[["bzImage",3,1788344684,33188,1000,1000,"e3c50838.bin"]]}\n'
            (old_fs / 'filesystem.json').write_bytes(old_metadata)
            (old_fs / 'e3c50838.bin').write_bytes(b'old')
            (old_fs / 'nested/canary.bin').write_bytes(b'old-runtime\x00\xff\r\n')
            html = runtime / 'index.html'
            original_html = (b'<!doctype html>\n<script>\n'
                             b'const bzimageUrl = "./filesystem/e3c50838.bin";\n'
                             b'const unrelated = "keep";\n</script>\n')
            html.write_bytes(original_html)
            sibling = work / 'untouched.bin'
            sibling.write_bytes(b'outside-runtime-canary\x00')
            before = snapshot(old_fs)
            if source_present:
                source_dir.mkdir()
                payload = b'new-fixture-image\x00\xff'
                # Reduced metadata fixture, with the actual compact fsroot row
                # schema and numeric fields. Not a bootable Linux filesystem.
                metadata = {'fsroot': [['bzImage', len(payload), 1788344684,
                                        33188, 1000, 1000, 'cafebabe.bin']]}
                (source_dir / 'filesystem.json').write_bytes(
                    (json.dumps(metadata, separators=(',', ':')) + '\n').encode('ascii'))
                (source_dir / 'cafebabe.bin').write_bytes(payload)
                (source_dir / 'nested').mkdir()
                (source_dir / 'nested/new.txt').write_bytes(b'new-file\n')
            expected_source = snapshot(source_dir)

            # Validate the production rm target as an absolute owned path
            # before executing the complete script that performs its removal.
            resolved_runtime = runtime.resolve(strict=True)
            removal_target = old_fs.resolve(strict=True)
            if removal_target.parent != resolved_runtime or not removal_target.is_relative_to(work):
                raise RuntimeError('Refusing production removal outside private runtime')
            if (script.parent / '..').resolve(strict=True) != resolved_runtime:
                raise RuntimeError('Script-derived root differs from private runtime')

            env = dict(os.environ)
            for key in list(env):
                if key in ('BASH_ENV', 'ENV', 'SHELLOPTS', 'BASHOPTS') or key.startswith('BASH_FUNC_'):
                    env.pop(key, None)
            env['PATH'] = str(self.utility_bin)
            result = subprocess.run(
                [str(self.bash), '--noprofile', '--norc', bash_path(script)],
                cwd=str(unrelated if alternate_cwd else runtime), env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=20, check=False)
            self.assertEqual(script.read_bytes(), original_script, 'full script must remain unchanged')
            self.assertEqual(sibling.read_bytes(), b'outside-runtime-canary\x00')
            return {
                'status': result.returncode,
                'stderr': result.stderr.decode('utf-8', 'replace'),
                'before': before,
                'after': snapshot(old_fs),
                'original_html': original_html,
                'html': html.read_bytes(),
                'expected_source': expected_source,
                'source_after': snapshot(source_dir)
            }
        finally:
            if work.is_symlink():
                raise RuntimeError('Refusing cleanup of a replaced fixture root')
            target = work.resolve(strict=True)
            if target.parent != self.private_root or not target.name.startswith('wasm-sync-source-'):
                raise RuntimeError('Refusing recursive cleanup outside Main private WorkRoot')
            shutil.rmtree(target)

    def check_missing(self, alternate_cwd):
        result = self.run_sync(False, alternate_cwd)
        self.assertNotEqual(result['status'], 0, result['stderr'] + '\nold_tree_preserved=' + str(result['after'] == result['before']) + '; html_preserved=' + str(result['html'] == result['original_html']))
        self.assertIn('Missing filesystem source directory:', result['stderr'])
        self.assertEqual(result['after'], result['before'], 'all old files and empty directories must survive')
        self.assertEqual(result['html'], result['original_html'], 'index must be byte-identical')

    def check_success(self, alternate_cwd):
        result = self.run_sync(True, alternate_cwd)
        self.assertEqual(result['status'], 0, result['stderr'])
        self.assertEqual(result['after'], result['expected_source'], 'real cp must replace the old tree')
        self.assertEqual(result['source_after'], result['expected_source'], 'source remains unchanged')
        self.assertEqual(result['html'], result['original_html'].replace(b'e3c50838.bin', b'cafebabe.bin'))

    def test_missing_source_from_runtime(self):
        self.check_missing(False)

    def test_missing_source_from_unrelated_cwd(self):
        self.check_missing(True)

    def test_source_present_from_runtime(self):
        self.check_success(False)

    def test_source_present_from_unrelated_cwd(self):
        self.check_success(True)


if __name__ == '__main__':
    unittest.main()
