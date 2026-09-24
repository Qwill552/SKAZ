"""Build-only: render the unchanged skaz.svg with an installed Chrome/Edge.

Run this script, then build_icon.ps1 -Png ../_check/tts9/logo.png (from packaging).
End users receive skaz.ico and never need a renderer or build dependencies.
"""
from pathlib import Path
import os
import subprocess

ROOT = Path(__file__).resolve().parent.parent


def render():
    candidates = [Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Google/Chrome/Application/chrome.exe',
                  Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe']
    browser = next((path for path in candidates if path.is_file()), None)
    if browser is None:
        raise SystemExit('Install Chrome or Edge on the build machine to render skaz.svg')
    work = ROOT.parent / '_check/tts9'
    work.mkdir(parents=True, exist_ok=True)
    html, output = work / 'logo-render.html', work / 'logo.png'
    html.write_text('<!doctype html><style>html,body{margin:0;background:transparent}'
                    'svg{position:absolute;left:0;top:0;width:512px;height:512px}</style>'
                    + (ROOT / 'skaz.svg').read_text(encoding='utf-8'), encoding='utf-8')
    result = subprocess.run([
        str(browser), '--headless', '--disable-gpu', '--no-first-run', '--hide-scrollbars',
        '--default-background-color=00000000', '--window-size=512,512', '--force-device-scale-factor=1',
        f'--screenshot={output}', f'--user-data-dir={work / "render-profile"}', html.as_uri(),
    ], capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode or not output.is_file():
        raise SystemExit(result.stderr.decode(errors='replace'))
    print(output)


if __name__ == '__main__':
    render()
