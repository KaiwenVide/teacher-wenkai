from __future__ import annotations
import importlib.util
import os
import shutil
import subprocess
import sys
from . import __version__
from .common import SKILL_ROOT
from .providers import PROVIDERS
from .lifesciences import catalog


def doctor():
    modules = {m: bool(importlib.util.find_spec(m)) for m in ['pypdf','pypdfium2','jsonschema','yaml','bibtexparser','numpy','pandas','scipy','statsmodels','matplotlib','openpyxl','nbformat','nbclient','pydeseq2','requests']}
    binaries = {name: shutil.which(name) for name in ['python3','paperclip','scansci-pdf']}
    database = catalog()
    counts = {key: sum(v['backend'] == key for v in database['providers'].values()) for key in ['native']}
    return {'skill_root': str(SKILL_ROOT), 'python': sys.executable, 'python_version': sys.version.split()[0],
            'skill_version': __version__, 'modules': modules, 'executables': binaries, 'database_backends': counts,
            'credential_variable_present': {k: bool(os.environ.get(k)) for k in ['NCBI_API_KEY','NCBI_EMAIL','OPENALEX_API_KEY','CROSSREF_MAILTO','UNPAYWALL_EMAIL','S2_API_KEY','CORE_API_KEY','PAPERCLIP_API_KEY']},
            'literature_api_providers': len(PROVIDERS), 'network_or_auth_checked': False,
            'note': 'Installed software is not verified authentication or a successful network request. Only environment variable presence is inspected.'}


def run_adapter(name, args):
    args = list(args)
    if args[:1] == ['--']: args = args[1:]
    if name in ['citation','reader-math','jats','arxiv-parse','openalex-abstract']:
        from .format_tools import run
        return run(name, args)
    if name in ['paginate', 'publisher-download']:
        from .retrieval_tools import run
        return run(name, args)
    if name == 'paperclip':
        binary = shutil.which('paperclip')
        if not binary: raise ValueError('Paperclip CLI is not installed; native search and download remain available')
        allowed = {'--help','--version','search','lookup','grep','scan','cat','head','tail','ls','tree','wc','map','reduce','results','ask-image','skill'}
        if not args or args[0] not in allowed: raise ValueError('This bridge exposes corpus retrieval only')
        if any(x == '--api-key' or x.startswith('--api-key=') or x in ['--import-bundle','--save-as'] for x in args):
            raise ValueError('Use environment credentials; account and server-state changes are not exposed')
        return subprocess.call([binary, *args])
    raise ValueError('Unknown adapter')


def scansci_request(identifier, output_dir=None):
    arguments = {'identifier': identifier, 'strategy': 'legal_only', 'scihub_enabled': False, 'use_tor': False}
    if output_dir: arguments['output_dir'] = str(output_dir)
    return {'tool': 'scansci_pdf_download', 'arguments': arguments, 'status': 'request_prepared_not_executed',
            'required_configuration': {'scihub_enabled': False, 'download_strategy': 'legal_only'},
            'next_action': 'Check the separately installed tool schema and authorization. Use native lawful download if unavailable.'}
