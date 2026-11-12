"""Build a local, allowlisted GitHub source candidate without overwrites.

The candidate is never pushed or submitted. Operator databases, private
evidence, raw reports, one-off payment runners, and seller screenshots with
internal ledger identifiers are excluded by construction.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import zipfile

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent

ROOT_FILES = (
    '.dockerignore', '.env.example', '.env.deploy.example', '.gitignore',
    'LICENSE', 'README.md', 'THIRD_PARTY.md', 'requirements.txt', 'pytest.ini',
    'ARCHITECTURE.md', 'SECURITY.md', 'POSITIONING.md', 'QA-REPORT.md',
    'OPTION-B-READINESS.md', 'OPTION-B-FINAL-VERIFICATION.md',
    'DEPLOYMENT-READINESS.md', 'DEPLOYMENT-GATE-REPORT.md',
    'FINAL-DEMO.md', 'SUBMISSION.md', 'ECONOMIC-DEMO.md',
    'Dockerfile', 'compose.yaml', 'compose.interactive.yaml',
    'agent.py', 'app.py', 'db.py', 'demo_quota.py', 'demo_economics.py',
    'engine.py', 'firewall.py', 'interactive_api.py', 'paypal_client.py',
    'public_agent.py', 'public_demo.py', 'settings.py', 'serve.py', 'local_server.py',
    'bootstrap.py', 'bootstrap.ps1', 'setup_local.py', 'start.ps1', 'stop.ps1',
    'prepare_deployment.py', 'migrate_deployment.py', 'package_submission.py',
    'initialize_interactive_quota.py', 'verify_deployment.py',
    'verify_http.py', 'verify_interactive.py', 'reproduce.py', 'evaluate.py',
    'verify_approved_session.py',  # Disabled CLI; imported by the mocked capture-cap tests.
    'checkout_return.html', 'migrations.sql', 'migrations_synthetic.sql',
    'demo-evidence.json', 'openapi.json', 'holdout.json',
    'test_agent_api.py', 'test_approved_workflow.py', 'test_checkout_return.py',
    'test_deployment.py', 'test_economic_demo.py', 'test_engine.py',
    'test_final_readiness.py', 'test_firewall.py', 'test_hardening.py',
    'test_interactive.py', 'test_paypal_client.py', 'test_publication_package.py',
)

SECRET_PATTERNS = (
    (re.compile(r'(?i)\bgsk_[A-Za-z0-9_-]{20,}'), 'provider token'),
    (re.compile(r'(?i)\bgh[pousr]_[A-Za-z0-9]{20,}'), 'GitHub token'),
    (re.compile(r'(?i)\bAKIA[0-9A-Z]{16}\b'), 'AWS access key'),
    (re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'), 'private key'),
    (re.compile(r'(?i)\bsk_live_[A-Za-z0-9]{12,}'), 'live provider key'),
)


def public_files() -> list[Path]:
    """Return a fixed publication allowlist; never collect by broad extension."""
    missing = [name for name in ROOT_FILES if not (ROOT / name).is_file()]
    if missing:
        raise FileNotFoundError('Required publication sources are missing: ' + ', '.join(missing))

    files = [ROOT / name for name in ROOT_FILES]
    frontend = ROOT / 'frontend'
    files.extend(frontend / name for name in ('package.json', 'package-lock.json', 'tsconfig.json', 'index.html'))
    files.extend(p for base in (frontend / 'src', frontend / 'public') for p in base.rglob('*') if p.is_file())
    files.extend(ROOT / 'assets' / name for name in (
        'buyer-desktop.jpg', 'buyer-mobile.jpg', 'buyer-tablet.jpg',
    ))
    missing_assets = [p.relative_to(ROOT).as_posix() for p in files if not p.is_file()]
    if missing_assets:
        raise FileNotFoundError('Required publication assets are missing: ' + ', '.join(missing_assets))
    return sorted(set(files))


def _private_identifiers() -> list[bytes]:
    evidence = ROOT / '.local' / 'private-evidence' / 'sandbox-verification.json'
    if not evidence.is_file():
        return []
    try:
        record = json.loads(evidence.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return []
    values = [record.get(k) for k in ('order_id', 'authorization_id', 'capture_id', 'session_id')]
    void = record.get('void_test', {})
    if isinstance(void, dict):
        values.extend(void.get(k) for k in ('order_id', 'authorization_id', 'session_id'))
    return [str(v).encode() for v in values if isinstance(v, str) and v]


def scan(files: list[Path]) -> list[dict[str, str]]:
    """Scan only the allowlisted bytes; never return or print a matched value."""
    configured = dotenv_values(ROOT / '.env')
    credential_names = {
        'DATABASE_URL', 'READER_DATABASE_URL', 'PAYPAL_CLIENT_ID',
        'PAYPAL_SECRET', 'GROQ_API_KEY', 'LOCAL_API_KEY',
        'DB_ADMIN_PASSWORD', 'DB_APP_PASSWORD', 'DB_READER_PASSWORD',
    }
    secrets = [v.encode() for k, v in configured.items()
               if v and (k.upper() in credential_names or
                         any(part in k.upper() for part in ('SECRET', 'PASSWORD', 'API_KEY')))]
    identifiers = _private_identifiers()
    findings: list[dict[str, str]] = []
    for path in files:
        data = path.read_bytes()
        relative = path.relative_to(ROOT).as_posix()
        if any(value in data for value in secrets):
            findings.append({'file': relative, 'category': 'configured secret'})
        if any(value in data for value in identifiers):
            findings.append({'file': relative, 'category': 'private historical transaction reference'})
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            text = ''
        for pattern, category in SECRET_PATTERNS:
            if pattern.search(text):
                findings.append({'file': relative, 'category': category})
    return findings


def create_archive(output: Path) -> tuple[dict, Path]:
    output = output if output.is_absolute() else ROOT / output
    output = output.resolve()
    manifest_path = output.with_suffix('.manifest.json')
    if output.exists() or manifest_path.exists():
        raise FileExistsError('Refusing to overwrite an existing candidate or manifest.')

    files = public_files()
    findings = scan(files)
    report = {'files_scanned': len(files), 'findings': findings, 'published': False}
    if findings:
        raise RuntimeError('Public package scan failed; no archive was written.')

    manifest = [
        {'path': p.relative_to(ROOT).as_posix(), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
         'bytes': p.stat().st_size}
        for p in files
    ]
    manifest_bytes = json.dumps(manifest, indent=2).encode('utf-8')
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents a race from replacing a previously saved package.
    with output.open('xb') as raw, zipfile.ZipFile(raw, 'w', zipfile.ZIP_DEFLATED) as archive:
        for item in manifest:
            archive.write(ROOT / item['path'], arcname='queryvault/' + item['path'])
        archive.writestr('queryvault/SOURCE-MANIFEST.json', manifest_bytes)
    try:
        with manifest_path.open('xb') as handle:
            handle.write(manifest_bytes)
    except Exception:
        # Do not remove an archive after a later manifest write failure; the
        # archive remains intact and the collision is reported to the operator.
        raise
    return report, manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='new local archive path; existing files are never replaced')
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    output = args.output or Path('submission') / f'queryvault-source-{stamp}.zip'
    report, manifest = create_archive(output)
    print(json.dumps(report, indent=2))
    print(f'Local candidate: {Path(output).as_posix()}')
    print(f'Manifest: {manifest.relative_to(ROOT).as_posix()}')
    print('Nothing was pushed, published or submitted.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
