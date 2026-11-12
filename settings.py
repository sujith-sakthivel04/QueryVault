"""Explicit deployment boundary. Public mode never loads the operator .env."""
from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent


class ConfigurationError(ValueError):
    pass


def load_local_environment():
    if os.getenv('QUERYVAULT_MODE', 'local') == 'local':
        load_dotenv(ROOT / os.getenv('QUERYVAULT_ENV_FILE', '.env'))


def secret(name, env):
    value, filename = env.get(name, ''), env.get(name + '_FILE', '')
    if value and filename:
        raise ConfigurationError(f'Set only one of {name} and {name}_FILE')
    if filename:
        try:
            value = Path(filename).read_text(encoding='utf-8').strip()
        except OSError:
            raise ConfigurationError(f'{name}_FILE cannot be read') from None
    return value


@dataclass(frozen=True)
class Settings:
    mode: str = 'local'
    public_origin: str = ''
    reader_url: str = field(default='', repr=False)
    frontend: Path = ROOT / 'frontend' / 'dist'
    quota_path: Path | None = None
    interactive_enabled: bool = False
    provider_key: str = field(default='', repr=False)
    provider_model: str = 'openai/gpt-oss-20b'
    quota_kill_file: Path | None = None

    @property
    def public_demo(self):
        return self.mode == 'public_demo'

    @property
    def public_interactive(self):
        return self.mode == 'public_interactive'

    @property
    def public_mode(self):
        return self.mode in ('public_demo', 'public_interactive')

    @property
    def allowed_hosts(self):
        return [urlsplit(self.public_origin).hostname] if self.public_mode else ['127.0.0.1', 'localhost', 'testserver']

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        mode = env.get('QUERYVAULT_MODE', 'local')
        if mode not in ('local', 'public_demo', 'public_interactive'):
            raise ConfigurationError('QUERYVAULT_MODE must be local, public_demo or public_interactive')
        if mode == 'local':
            return cls()
        origin = env.get('QUERYVAULT_PUBLIC_ORIGIN', '')
        try:
            url = urlsplit(origin)
            valid = (url.hostname and '*' not in url.hostname and url.port != 0 and not url.username and not url.password
                     and not url.query and not url.fragment and url.path in ('', '/')
                     and (url.scheme == 'https' or (url.scheme == 'http' and url.hostname in ('localhost', '127.0.0.1'))))
        except ValueError:
            valid = False
        if not valid or origin.endswith('/'):
            raise ConfigurationError('QUERYVAULT_PUBLIC_ORIGIN must be an exact HTTPS origin without a trailing slash; HTTP is allowed only on loopback for testing')
        if env.get('QUERYVAULT_DATASET') != 'synthetic-logistics-v1':
            raise ConfigurationError('Public demo requires QUERYVAULT_DATASET=synthetic-logistics-v1')
        # No public process may load operator/payment credentials. Public AI
        # accepts only a separately mounted provider-key file and only in B2.
        forbidden = ('LOCAL_API_KEY', 'LOCAL_API_KEY_FILE', 'DATABASE_URL', 'DATABASE_URL_FILE', 'PAYPAL_CLIENT_ID', 'PAYPAL_CLIENT_ID_FILE', 'PAYPAL_SECRET', 'PAYPAL_SECRET_FILE', 'MIGRATION_DATABASE_URL', 'MIGRATION_DATABASE_URL_FILE', 'MIGRATION_DB_PASSWORD', 'MIGRATION_DB_PASSWORD_FILE', 'DB_ADMIN_PASSWORD', 'DB_APP_PASSWORD')
        if mode == 'public_demo':
            forbidden += ('GROQ_API_KEY', 'GROQ_API_KEY_FILE')
        else:
            forbidden += ('GROQ_API_KEY',)
        if any(env.get(k) for k in forbidden):
            raise ConfigurationError('Public mode must not contain operator, writer, PayPal or inline provider credentials')
        reader = secret('READER_DATABASE_URL', env)
        try:
            parsed = urlsplit(reader)
            valid_reader = (parsed.scheme in ('postgres', 'postgresql') and parsed.hostname
                            and parsed.username and parsed.password and parsed.path.strip('/') and parsed.port != 0)
        except ValueError:
            valid_reader = False
        if not valid_reader:
            raise ConfigurationError('Public mode requires a valid READER_DATABASE_URL or READER_DATABASE_URL_FILE')
        if mode == 'public_demo':
            if env.get('GROQ_API_KEY_FILE'):
                raise ConfigurationError('The restricted public demo cannot load a provider key')
            return cls(mode, origin, reader)

        # B2 requires an independently named synthetic database, not the
        # private operator database used by local mode.
        if parsed.path.strip('/') != 'queryvault_interactive_demo':
            raise ConfigurationError('Interactive demo requires the dedicated queryvault_interactive_demo database')
        reader_file=env.get('READER_DATABASE_URL_FILE','')
        if not reader_file or not Path(reader_file).is_absolute():
            raise ConfigurationError('Interactive demo requires a mounted reader DSN secret file')
        try:
            Path(reader_file).resolve().relative_to(ROOT)
        except ValueError:
            pass
        else:
            raise ConfigurationError('Interactive reader DSN must be mounted outside the source tree')
        if parsed.username!='qv_interactive_reader':
            raise ConfigurationError('Interactive demo requires the dedicated query-only database role')
        if parsed.hostname not in ('db','localhost','127.0.0.1') and parse_qs(parsed.query).get('sslmode')!=['verify-full']:
            raise ConfigurationError('Remote interactive readers require sslmode=verify-full')
        enabled_value = env.get('QUERYVAULT_INTERACTIVE_ENABLED', 'false').strip().casefold()
        if enabled_value not in ('true', 'false'):
            raise ConfigurationError('QUERYVAULT_INTERACTIVE_ENABLED must be true or false')
        enabled = enabled_value == 'true'
        kill_value = env.get('QUERYVAULT_INTERACTIVE_KILL_SWITCH', 'false').strip().casefold()
        if kill_value not in ('true', 'false'):
            raise ConfigurationError('QUERYVAULT_INTERACTIVE_KILL_SWITCH must be true or false')
        quota_path_value = env.get('QUERYVAULT_QUOTA_DB_PATH', '')
        quota_path = Path(quota_path_value) if quota_path_value else None
        if not quota_path or not quota_path.is_absolute() or quota_path.name in ('', '.', '..') or str(quota_path) == ':memory:':
            raise ConfigurationError('Interactive demo requires an absolute persistent QUERYVAULT_QUOTA_DB_PATH')
        try:
            quota_resolved = quota_path.resolve(strict=False)
            quota_resolved.relative_to(ROOT)
        except ValueError:
            pass
        else:
            raise ConfigurationError('Quota state must be stored outside the source tree and static frontend')
        quota_kill_file = quota_path.parent / 'AI_DISABLED'
        if env.get('GROQ_API_KEY_FILE'):
            provider_path = Path(env['GROQ_API_KEY_FILE'])
            if not provider_path.is_absolute():
                raise ConfigurationError('Provider key file path must be absolute')
            try:
                provider_path.resolve().relative_to(ROOT)
            except ValueError:
                pass
            else:
                raise ConfigurationError('Provider key must be mounted outside the source tree')
        provider_key = secret('GROQ_API_KEY', env) if enabled else ''
        if enabled and (not provider_key or len(provider_key) < 20):
            raise ConfigurationError('Interactive AI is enabled but its mounted Groq key is missing or invalid')
        model = env.get('GROQ_MODEL', 'openai/gpt-oss-20b').strip()
        if not model or len(model) > 80 or any(ord(ch) < 33 for ch in model):
            raise ConfigurationError('GROQ_MODEL must be a short provider model identifier')
        return cls(mode, origin, reader, ROOT / 'frontend' / 'dist', quota_path, enabled and kill_value != 'true',
                   provider_key, model, quota_kill_file)
