"""Generate new ignored local Compose secrets. Never overwrite existing files."""
from pathlib import Path
import argparse
import os
import secrets


def prepare(target=None):
    target=Path(target) if target else Path(__file__).parent/'.local/deploy-secrets'
    target.mkdir(parents=True,exist_ok=True,mode=0o700)
    if os.name!='nt': target.chmod(0o700)
    values={'postgres_password':secrets.token_urlsafe(40),'reader_password':secrets.token_urlsafe(40)}
    paths=[target/n for n in (*values,'reader_database_url')]
    if any(p.exists() for p in paths):
        raise ValueError('Deployment secret files already exist; refusing to overwrite or rotate them')
    values['reader_database_url']='postgresql://qv_reader:'+values['reader_password']+'@db:5432/queryvault'
    for name,value in values.items():
        # Compose file-backed secrets preserve source permissions. Files must be
        # readable by the non-root container UID; their host directory is 0700.
        fd=os.open(target/name,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o444)
        with os.fdopen(fd,'w',encoding='utf-8') as out: out.write(value+'\n')
    return paths


def prepare_interactive(target=None):
    """Add Phase B2 secrets beside an older public_demo secret set once."""
    target=Path(target) if target else Path(__file__).parent/'.local/deploy-secrets'
    target.mkdir(parents=True,exist_ok=True,mode=0o700)
    if os.name!='nt': target.chmod(0o700)
    password=secrets.token_urlsafe(40)
    values={'interactive_reader_password':password,
            'interactive_reader_database_url':'postgresql://qv_interactive_reader:'+password+'@db:5432/queryvault_interactive_demo',
            'groq_api_key':''}
    paths=[target/name for name in values]
    if any(path.exists() for path in paths):
        raise ValueError('Interactive secret files already exist; refusing to overwrite or rotate them')
    for name,value in values.items():
        fd=os.open(target/name,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o444)
        with os.fdopen(fd,'w',encoding='utf-8') as out: out.write(value+'\n')
    return paths


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--interactive',action='store_true',help='add Phase B2-only reader/provider secret files')
    args=parser.parse_args()
    if args.interactive: prepare_interactive()
    else: prepare()
    print('Ignored Compose secret files created; no values displayed and no services started.')
