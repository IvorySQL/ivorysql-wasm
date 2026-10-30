"""Run the complete real build.sh in private fixtures; no real Docker/build.

Main only: existing Bash + real sed, with a clearly bounded external Docker
command fixture. Worker prepares this file but never executes it.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


DOCKER_FIXTURE = r'''#!/usr/bin/env bash
case "$1" in
    build|run) ;;
    *) exit 125 ;;
esac
printf '%s\0' "$@" > "$DOCKER_FIXTURE_LOG_DIR/$1.args"
printf '%s\n' "$1" >> "$DOCKER_FIXTURE_LOG_DIR/calls"
printf '%s' "$PWD" > "$DOCKER_FIXTURE_LOG_DIR/cwd"
printf '%s' "$IVORYSQL_VERSION" > "$DOCKER_FIXTURE_LOG_DIR/version"
if [ "$1" = build ]; then
    exit "$DOCKER_FIXTURE_BUILD_EXIT"
fi
exit "$DOCKER_FIXTURE_RUN_EXIT"
'''


def bash_path(value):
    value = Path(value).resolve()
    text = value.as_posix()
    if os.name == 'nt' and value.drive:
        return '/' + value.drive[0].lower() + text[2:]
    return text


class BuildExitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(os.environ['WASM_SOURCE_ROOT']).resolve() / 'packages/buildroot/build.sh'
        cls.bash = Path(os.environ['WASM_BASH']).resolve()
        cls.utility_bin = Path(os.environ['WASM_UTILITY_BIN']).resolve()
        cls.private_root = Path(os.environ['WASM_WORK_ROOT']).resolve(strict=True)
        if not cls.source.is_file() or not cls.bash.is_file() or not cls.private_root.is_dir():
            raise RuntimeError('Main must supply real source, existing Bash and private WorkRoot')
        if any(character.isspace() for character in str(cls.private_root)):
            raise RuntimeError('Use a private path without whitespace; path quoting is outside this root')
        if not any((cls.utility_bin / name).is_file() for name in ('sed', 'sed.exe')):
            raise RuntimeError('Existing real sed is required; no sed fixture permitted')
        # PATH is restricted below. Do not allow a failed fixture lookup to find
        # a real Docker executable and access a daemon/network by accident.
        for name in ('docker', 'docker.exe', 'docker.cmd', 'docker.bat'):
            if (cls.utility_bin / name).exists():
                raise RuntimeError('Utility directory must not contain Docker')

    def run_build(self, build_status, run_status):
        work = Path(tempfile.mkdtemp(prefix='wasm-build-exit-', dir=self.private_root)).resolve()
        if work.parent != self.private_root or not work.name.startswith('wasm-build-exit-'):
            raise RuntimeError('Refusing unexpected private work path')
        try:
            buildroot = work / 'packages/buildroot'
            runtime = work / 'packages/runtime'
            fixture_bin = work / 'command-fixture'
            logs = work / 'logs'
            for directory in (buildroot, runtime, fixture_bin, logs):
                directory.mkdir(parents=True)
            for name in ('tools', 'build', 'config'):
                (buildroot / name).mkdir()
            script = buildroot / 'build.sh'
            shutil.copyfile(self.source, script)  # complete selected script, no rewrites
            html = runtime / 'index.html'
            html.write_bytes(b'<script>const version = "old";</script>\n<!-- fixture canary -->\n')
            docker = fixture_bin / 'docker'
            docker.write_bytes(DOCKER_FIXTURE.encode('utf-8'))
            docker.chmod(0o755)

            env = dict(os.environ)
            for key in list(env):
                if key in ('BASH_ENV', 'ENV', 'SHELLOPTS', 'BASHOPTS') or key.startswith('BASH_FUNC_'):
                    env.pop(key, None)
            env['PATH'] = os.pathsep.join((str(fixture_bin), str(self.utility_bin)))
            env['DOCKER_FIXTURE_LOG_DIR'] = bash_path(logs)
            env['DOCKER_FIXTURE_BUILD_EXIT'] = str(build_status)
            env['DOCKER_FIXTURE_RUN_EXIT'] = str(run_status)
            result = subprocess.run(
                [str(self.bash), '--noprofile', '--norc', bash_path(script)],
                cwd=str(buildroot), env=env, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=20, check=False)
            if not (logs / 'calls').is_file():
                raise RuntimeError('Command fixture did not run: ' + result.stderr.decode('utf-8', 'replace'))
            # Real sed must have executed against only the private runtime file.
            if html.read_bytes() != b'<script>const version = "5.6";</script>\n<!-- fixture canary -->\n':
                raise RuntimeError('Real sed/private fixture setup failed; not a build-exit assertion')
            self.assertEqual(script.read_bytes(), self.source.read_bytes())
            self.assertEqual((logs / 'version').read_text(encoding='utf-8'), '5.6')
            calls = (logs / 'calls').read_text(encoding='utf-8').splitlines()
            build_args = (logs / 'build.args').read_bytes().decode('utf-8').split('\0')[:-1]
            self.assertEqual(build_args, ['build', '--build-arg', 'IVORYSQL_VERSION=5.6', '-t', 'buildroot', '.'])
            if (logs / 'run.args').exists():
                cwd = (logs / 'cwd').read_text(encoding='utf-8')
                run_args = (logs / 'run.args').read_bytes().decode('utf-8').split('\0')[:-1]
                self.assertEqual(run_args, [
                    'run', '--rm', '-v', cwd + '/tools:/tools',
                    '-v', cwd + '/build:/build', '-v', cwd + '/config:/config',
                    '-e', 'IVORYSQL_VERSION=5.6', '-ti', '--platform', 'linux/amd64', 'buildroot'
                ])
            return result.returncode, calls
        finally:
            target = work.resolve()
            if target.parent != self.private_root or not target.name.startswith('wasm-build-exit-'):
                raise RuntimeError('Refusing recursive cleanup outside owned private work')
            shutil.rmtree(target)

    def test_build_failure_stops_before_successful_run(self):
        status, calls = self.run_build(7, 0)
        self.assertEqual(calls, ['build'])
        self.assertEqual(status, 7)

    def test_build_failure_preserves_its_status_not_later_run_status(self):
        status, calls = self.run_build(23, 9)
        self.assertEqual(calls, ['build'])
        self.assertEqual(status, 23)

    def test_success_keeps_build_then_run_and_existing_arguments(self):
        status, calls = self.run_build(0, 0)
        self.assertEqual(calls, ['build', 'run'])
        self.assertEqual(status, 0)

    def test_run_failure_after_successful_build_remains_visible(self):
        status, calls = self.run_build(0, 9)
        self.assertEqual(calls, ['build', 'run'])
        self.assertEqual(status, 9)


if __name__ == '__main__':
    unittest.main()
