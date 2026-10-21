"""Bounded, checksum-verified source acquisition; no setup/build/import execution."""
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
import zipfile

MAX_DOWNLOAD = 20 * 1024 * 1024
MAX_SOURCE = 50 * 1024 * 1024
MAX_MEMBERS = 10000


def fetch(url, limit=MAX_DOWNLOAD):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in ('pypi.org', 'files.pythonhosted.org'):
        raise ValueError('Only HTTPS PyPI metadata and pythonhosted artifacts are accepted')
    with urlopen(Request(url, headers={'User-Agent': 'semver-lie-detector/0.1'}), timeout=30) as response:
        final = urlparse(response.geturl())
        if final.scheme != 'https' or final.hostname not in ('pypi.org', 'files.pythonhosted.org'):
            raise ValueError('Unexpected download redirect')
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Download exceeds byte limit')
    return data


def metadata(package, version=None):
    suffix = '/' + quote(version, safe='') if version else ''
    return json.loads(fetch(f'https://pypi.org/pypi/{quote(package, safe="")}{suffix}/json'))


def stable_versions(project):
    versions = []
    for version, files in project['releases'].items():
        if re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', version) and files:
            versions.append(version)
    return sorted(versions, key=lambda v: tuple(map(int, v.split('.'))))


def require_consecutive(project, before, after):
    versions = stable_versions(project)
    if before not in versions or after not in versions or versions.index(after) != versions.index(before) + 1:
        raise ValueError('Select consecutive stable three-component releases from PyPI (including yanked releases)')


def extract_sources(data, filename, destination):
    """Copy regular .py files only; reject traversal/links and bound expanded size."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    entries = []
    archive = None
    expanded = 0
    if filename.endswith('.zip'):
        archive = zipfile.ZipFile(io.BytesIO(data))
        for m in archive.infolist():
            is_link = ((m.external_attr >> 16) & 0o170000) == 0o120000
            entries.append((m.filename, m.file_size, m.is_dir(), is_link, m))
        reader = archive.open
    elif filename.endswith(('.tar.gz', '.tgz', '.tar.bz2', '.tar.xz', '.tar')):
        archive = tarfile.open(fileobj=io.BytesIO(data), mode='r:*')
        for index, m in enumerate(archive):
            if index >= MAX_MEMBERS:
                archive.close()
                raise ValueError('Archive has too many members')
            expanded += m.size
            if expanded > MAX_SOURCE:
                archive.close()
                raise ValueError('Expanded archive exceeds byte limit')
            entries.append((m.name, m.size, m.isdir(), not (m.isfile() or m.isdir()), m))
        reader = archive.extractfile
    else:
        raise ValueError('Unsupported source archive format')
    try:
        if len(entries) > MAX_MEMBERS:
            raise ValueError('Archive has too many members')
        if sum(entry[1] for entry in entries) > MAX_SOURCE:
            raise ValueError('Expanded archive exceeds byte limit')
        total, seen = 0, set()
        for name, size, directory, special, entry in entries:
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name or special:
                raise ValueError(f'Unsafe archive member: {name}')
            if directory or path.suffix != '.py':
                continue
            if path in seen:
                raise ValueError(f'Duplicate source member: {name}')
            seen.add(path)
            total += size
            if total > MAX_SOURCE:
                raise ValueError('Expanded source exceeds byte limit')
            target = destination.joinpath(*path.parts)
            # Refuse preexisting symlinks/files, including parent symlinks.
            if not target.resolve().is_relative_to(destination.resolve()) or target.exists():
                raise ValueError('Extraction destination must be empty and contained')
            target.parent.mkdir(parents=True, exist_ok=True)
            with reader(entry) as f:
                payload = f.read(min(size, MAX_SOURCE) + 1)
            if len(payload) != size:
                raise ValueError('Archive member size mismatch')
            target.write_bytes(payload)
        if not seen:
            raise ValueError('Archive contains no Python source')
        top = {p.parts[0] for p in seen}
        return destination / next(iter(top)) if len(top) == 1 and (destination / next(iter(top))).is_dir() else destination
    finally:
        archive.close()


def acquire(package, version, module, destination):
    release = metadata(package, version)
    artifacts = sorted((f for f in release['urls'] if f['packagetype'] == 'sdist'), key=lambda f: f['filename'])
    if not artifacts:
        raise ValueError(f'{package} {version} has no source distribution; wheels/native APIs are unsupported')
    artifact = artifacts[0]
    data = fetch(artifact['url'])
    digest = hashlib.sha256(data).hexdigest()
    if digest != artifact['digests']['sha256']:
        raise ValueError('Source distribution SHA256 mismatch')
    root = extract_sources(data, artifact['filename'], destination)
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', module):
        raise ValueError('--module must be one top-level import name')
    candidates = []
    for base in [root, root / 'src', root / 'lib']:
        directory, file = base / module, base / (module + '.py')
        if (directory / '__init__.py').is_file():
            candidates.append(directory)
        if file.is_file():
            candidates.append(file)
    if len(candidates) != 1:
        raise ValueError(f'Cannot uniquely locate module {module}; use local mode for nonstandard or namespace layouts')
    return candidates[0], {'package': package, 'version': version, 'filename': artifact['filename'],
                           'url': artifact['url'], 'sha256': digest, 'yanked': bool(artifact.get('yanked'))}
