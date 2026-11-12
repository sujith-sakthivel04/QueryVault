"""One-time explicit initialization of persistent public-interactive quotas."""
import os
from pathlib import Path
import sys

from demo_quota import DemoQuotaStore


def main():
    value=os.environ.get('QUERYVAULT_QUOTA_DB_PATH','')
    path=Path(value) if value else None
    if path is None or not path.is_absolute():
        raise ValueError('Set an absolute QUERYVAULT_QUOTA_DB_PATH on the persistent quota volume')
    store=DemoQuotaStore(path)
    if path.exists():
        store.validate()
        print('Persistent demo quota state already exists; no state was reset.')
        return 0
    store.initialize()
    store.validate()
    print('Persistent demo quota state initialized explicitly; provider and financial state were not accessed.')
    return 0


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'Interactive quota initialization failed ({type(exc).__name__}); state was not reset.',file=sys.stderr)
        raise SystemExit(1)
