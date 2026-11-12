from package_submission import ROOT, create_archive, public_files


def test_publication_allowlist_keeps_runtime_sources_and_excludes_private_artifacts():
    names = {path.relative_to(ROOT).as_posix() for path in public_files()}
    assert {'app.py', 'interactive_api.py', 'firewall.py', 'migrations_synthetic.sql',
            'frontend/package-lock.json', 'frontend/public/favicon.svg', 'demo-evidence.json',
            'package_submission.py', 'test_publication_package.py', 'local_server.py',
            'verify_approved_session.py'} <= names
    assert not {
        '.env', 'evaluation.json', 'sandbox-verification.json',
        'paypal-reconciliation-audit.json', 'checkout-diagnosis.json',
        'test-results.xml', 'test_run.py', 'sandbox_lifecycle.py',
        'import_agent_evidence.py', 'assets/seller-desktop.jpg',
        'assets/seller-tablet.jpg', 'assets/seller-mobile.jpg',
    } & names


def test_candidate_builder_never_overwrites_existing_archive(tmp_path):
    target = tmp_path / 'preserve.zip'
    target.write_bytes(b'keep existing candidate')

    try:
        create_archive(target)
    except FileExistsError:
        pass
    else:
        raise AssertionError('existing archive should be preserved')

    assert target.read_bytes() == b'keep existing candidate'
