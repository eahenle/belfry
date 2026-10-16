"""Exercise build command construction without requiring the macOS toolchain."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent


class MacBuildTests(unittest.TestCase):
    def test_library_parsing_is_only_enabled_for_main_app(self):
        # Removing the app's -parse-as-library flag must fail this regression.
        # Stub only platform tools; execute the real build script in isolation.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'checkout with spaces'
            (root / 'scripts').mkdir(parents=True)
            shutil.copy2(ROOT / 'scripts/build-mac.sh', root / 'scripts/build-mac.sh')
            shutil.copytree(ROOT / 'mac', root / 'mac')
            tools = Path(temporary) / 'tools'
            tools.mkdir()
            log = Path(temporary) / 'commands.jsonl'
            stub = f'#!{sys.executable}\n' + '''\
import json
import os
from pathlib import Path
import sys

name = Path(sys.argv[0]).name
if name == 'uname':
    print('Darwin' if sys.argv[1] == '-s' else 'arm64')
else:
    with open(os.environ['BUILD_COMMAND_LOG'], 'a') as output:
        output.write(json.dumps([name, *sys.argv[1:]]) + '\\n')
'''
            for name in ('uname', 'xcrun', 'codesign'):
                path = tools / name
                path.write_text(stub)
                path.chmod(0o755)
            environment = {
                **os.environ,
                'PATH': str(tools) + os.pathsep + os.environ.get('PATH', ''),
                'BUILD_COMMAND_LOG': str(log),
            }
            result = subprocess.run(
                ['bash', str(root / 'scripts/build-mac.sh')],
                env=environment, capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            commands = [json.loads(line) for line in log.read_text().splitlines()]
            compiles = [command for command in commands if command[:2] == ['xcrun', 'swiftc']]
            self.assertEqual(len(compiles), 3)
            for source, is_app in (
                ('Sources/NotificationWidget.swift', True),
                ('Helpers/Keychain.swift', False),
                ('Helpers/DockBadge.swift', False),
            ):
                with self.subTest(source=source):
                    matches = [command for command in compiles if str(root / 'mac' / source) in command]
                    self.assertEqual(len(matches), 1)
                    self.assertEqual('-parse-as-library' in matches[0], is_app)
