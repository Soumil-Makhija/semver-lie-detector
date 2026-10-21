import argparse
import json
from pathlib import Path
import sys
import tempfile
import tarfile
import zipfile
from urllib.error import URLError
from .compare import compare, version_policy
from .surface import scan
from .pypi import acquire, metadata, require_consecutive


def markdown(report):
    def safe(value):
        # Escape externally supplied text in shareable Markdown.
        return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('`', '&#96;').replace('|', '&#124;').replace('\n', ' ')
    v, summary = report['versions'], report['summary']
    lines = ['# Static API compatibility report', '',
             f"{safe(v['before'])} → {safe(v['after'])} ({v['bump']})", '',
             f"Suspected SemVer violation: **{str(report['suspected_violation']).lower()}**", '',
             f"Coverage: {report['analysis']}. {summary['breaking']} breaking findings; {summary['review']} changes to review; {summary['added']} added symbols.", '',
             'Static evidence only. An empty finding list does not prove runtime compatibility.', '',
             '| Symbol | Rule | Evidence |', '| --- | --- | --- |']
    for f in report['findings']:
        evidence = f['message']
        if f['witness']:
            evidence += ' — ' + json.dumps(f['witness'], sort_keys=True)
        lines.append(f"| {safe(f['symbol'])} | {f['severity']}: {f['rule']} | {safe(evidence)} |")
    if report['warnings']:
        lines += ['', '## Coverage warnings', ''] + ['- ' + safe(w) for w in report['warnings']]
    if report.get('provenance'):
        lines += ['', '## Source artifacts', '']
        for item in report['provenance']:
            lines.append(f"- {safe(item['filename'])}; SHA256: {safe(item['sha256'])}; yanked: {item['yanked']}")
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Find static Python public API breaks; never imports target code.')
    commands = parser.add_subparsers(dest='command', required=True)
    local = commands.add_parser('local', help='Compare import source directories or .py files')
    local.add_argument('before', type=Path)
    local.add_argument('after', type=Path)
    remote = commands.add_parser('pypi', help='Compare consecutive stable PyPI source releases')
    remote.add_argument('package')
    remote.add_argument('--module', required=True, help='Top-level Python import name, e.g. click')
    for sub in (local, remote):
        sub.add_argument('--before-version', required=True)
        sub.add_argument('--after-version', required=True)
        sub.add_argument('--format', choices=['json', 'markdown'], default='json')
        sub.add_argument('--output', type=Path)
        sub.add_argument('--fail-on-partial', action='store_true', help='Return 3 when analysis has coverage warnings and no violation')
    args = parser.parse_args(argv)
    try:
        version_policy(args.before_version, args.after_version)
        provenance = []
        with tempfile.TemporaryDirectory(prefix='semver-lie-') as temp:
            if args.command == 'pypi':
                require_consecutive(metadata(args.package), args.before_version, args.after_version)
                before, a = acquire(args.package, args.before_version, args.module, Path(temp) / 'before')
                after, b = acquire(args.package, args.after_version, args.module, Path(temp) / 'after')
                provenance = [a, b]
            else:
                before, after = args.before, args.after
            report = compare(scan(before), scan(after), args.before_version, args.after_version)
        report['provenance'] = provenance
        report['comparison'] = {'source': args.command, 'consecutive_verified': args.command == 'pypi', 'release_order': 'stable three-component releases with artifacts; includes yanked releases' if args.command == 'pypi' else 'versions supplied by caller'}
        output = json.dumps(report, indent=2, sort_keys=True) + '\n' if args.format == 'json' else markdown(report)
        if args.output:
            args.output.write_text(output, encoding='utf-8')
        else:
            sys.stdout.write(output)
        if report['suspected_violation']:
            return 1
        return 3 if args.fail_on_partial and report['analysis'] == 'partial' else 0
    except (OSError, ValueError, KeyError, TypeError, EOFError, URLError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(f'semver-lie: {exc}', file=sys.stderr)
        return 2
