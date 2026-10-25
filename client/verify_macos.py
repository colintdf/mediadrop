"""Reject an installer if any bundled Mach-O requires a newer macOS."""
from pathlib import Path
import plistlib
import re
import subprocess
import sys


def minimum_versions(output):
    result = []
    for command in re.split(r'Load command \d+', output):
        if re.search(r'\bcmd LC_BUILD_VERSION\b', command):
            match = re.search(r'\bminos (\d+(?:\.\d+){0,2})', command)
        elif re.search(r'\bcmd LC_VERSION_MIN_MACOSX\b', command):
            match = re.search(r'\bversion (\d+(?:\.\d+){0,2})', command)
        else:
            continue
        if match:
            result.append(tuple(int(n) for n in match[1].split('.')))
    return result


def verify(app, maximum=(14, 0, 0)):
    info = plistlib.loads((app/'Contents/Info.plist').read_bytes())
    declared = tuple(map(int, info['LSMinimumSystemVersion'].split('.')))
    assert (declared + (0, 0))[:3] <= maximum, 'Info.plist requires a newer macOS'
    binaries = list((app/'Contents/MacOS').iterdir()) + list((app/'Contents/Resources/Tools').iterdir()) + list((app/'Contents/Frameworks').iterdir())
    for binary in binaries:
        versions = minimum_versions(subprocess.check_output(['otool', '-l', str(binary)], text=True))
        assert versions, f'No macOS deployment version found in {binary}'
        for version in versions:
            assert (version + (0, 0))[:3] <= maximum, f'{binary.name} requires macOS {version}, newer than {maximum}'
    print(f'PASS: app and all {len(binaries)} bundled binaries support macOS 14.0')


if __name__ == '__main__':
    verify(Path(sys.argv[1]))
