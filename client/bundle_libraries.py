"""Relocate the Homebrew helper libraries into the app; reject escaped deps."""
from pathlib import Path
import subprocess
import shutil
import sys

app = Path(sys.argv[1]).resolve()
frameworks = app/'Contents/Frameworks'
frameworks.mkdir(exist_ok=True)
seen = set()

def relocate(binary):
    binary = Path(binary)
    if str(binary) in seen:
        return
    seen.add(str(binary))
    rows = subprocess.check_output(['otool','-L',str(binary)],text=True).splitlines()[1:]
    for row in rows:
        dep = row.strip().split(' (')[0]
        if dep.startswith(('/usr/lib/','/System/Library/','@')):
            continue
        source = Path(dep)
        target = frameworks/source.name
        if not target.exists():
            shutil.copyfile(source.resolve(),target)
            target.chmod(0o755)
            subprocess.run(['install_name_tool','-id','@rpath/'+target.name,str(target)],check=True)
            relocate(target)
        subprocess.run(['install_name_tool','-change',dep,'@rpath/'+target.name,str(binary)],check=True)

for executable in (app/'Contents/Resources/Tools').iterdir():
    relocate(executable)
    subprocess.run(['install_name_tool','-add_rpath','@executable_path/../../Frameworks',str(executable)],check=True)
# All dynamic references must now resolve within the bundle or system paths.
for binary in list((app/'Contents/Resources/Tools').iterdir()) + list(frameworks.iterdir()):
    output = subprocess.check_output(['otool','-L',str(binary)],text=True)
    assert '/opt/homebrew/' not in output and '/usr/local/' not in output, output
