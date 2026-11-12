"""Cross-platform local bootstrap. Requires Python 3.13+, Node 22+, PostgreSQL tools."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
def main():
    os.chdir(ROOT)
    if sys.version_info<(3,13): raise SystemExit('Python 3.13+ is required by the tested dependency lock.')
    venv=ROOT/'.venv'
    if not venv.exists(): subprocess.run([sys.executable,'-m','venv',str(venv)],check=True)
    python=venv/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    npm=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
    if not npm: raise SystemExit('Install Node.js 22+ (including npm), then rerun bootstrap.py.')
    for command,cwd in [([str(python),'-m','pip','install','-r','requirements.txt'],ROOT),([str(python),'setup_local.py'],ROOT),([npm,'ci','--legacy-peer-deps'],ROOT/'frontend'),([npm,'run','build'],ROOT/'frontend')]:
        subprocess.run(command,cwd=cwd,check=True)
    print('Ready. Run the .venv Python with: -m uvicorn app:app --host 127.0.0.1 --port 8000')

if __name__=='__main__': main()
