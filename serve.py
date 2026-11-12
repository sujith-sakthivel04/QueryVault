"""Production-style public entrypoint. Does not load .env or migrate data."""
import argparse
import os
import sys
from settings import Settings, ConfigurationError


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='Validate configuration without starting a server')
    args=parser.parse_args()
    try:
        cfg=Settings.from_env()
        if not cfg.public_mode:
            raise ConfigurationError('Production startup requires explicit public mode; use start.ps1 for local operator development')
        if cfg.public_interactive:
            from demo_quota import DemoQuotaStore
            DemoQuotaStore(cfg.quota_path).validate()
        port=int(os.getenv('PORT', '8000'))
        if not 1<=port<=65535:
            raise ConfigurationError('PORT must be between 1 and 65535')
        if args.check:
            print('Public-mode configuration is valid; no network connection or migration was made.')
            return 0
        import uvicorn
        uvicorn.run('app:create_app',factory=True,host=os.getenv('QUERYVAULT_HOST','127.0.0.1'),port=port,
                    workers=1,proxy_headers=False,access_log=False,limit_concurrency=16,
                    timeout_keep_alive=5,timeout_graceful_shutdown=10)
        return 0
    except (ConfigurationError,ValueError):
        # Never print arbitrary env content, connection strings or secret filenames.
        print('Public-mode configuration is invalid. Check required deployment settings in DEPLOYMENT-READINESS.md.',file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
