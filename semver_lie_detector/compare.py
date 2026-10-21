"""Call-domain comparison with reproducible rejected-call witnesses."""
import inspect
import itertools
import re
from .surface import Surface

P = inspect.Parameter


def version_policy(old, new):
    pattern = r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?'
    if not re.fullmatch(pattern, old) or not re.fullmatch(pattern, new):
        raise ValueError('Versions must be stable MAJOR.MINOR.PATCH (optional build metadata); prerelease/PEP 440 versions are not classified')
    a = tuple(map(int, old.split('+')[0].split('.')))
    b = tuple(map(int, new.split('+')[0].split('.')))
    if b <= a:
        raise ValueError('New version must be greater than old version')
    kind = 'major' if b[0] != a[0] else 'minor' if b[1] != a[1] else 'patch'
    return kind, a[0] >= 1 and kind in ('minor', 'patch')


def bind_call(signature, args, kwargs):
    # inspect.bind on older Python versions rejects a positional-only name in
    # **kwargs even when that positional parameter has a default. Rename the
    # positional-only slots for binding; their names are not part of the API.
    reserved = set(signature.parameters) | set(kwargs)
    params = []
    for index, param in enumerate(signature.parameters.values()):
        if param.kind == P.POSITIONAL_ONLY:
            name = f'__slot_{index}'
            while name in reserved:
                name += '_'
            reserved.add(name)
            param = param.replace(name=name)
        params.append(param)
    return signature.replace(parameters=params).bind(*args, **kwargs)


def rejected_call(old, new):
    """Enumerate the finite binding equivalence classes of two Python signatures.

    Keyword subsets are exhaustive, capped at 12 distinct names; larger APIs
    yield a coverage warning. Values are irrelevant to argument binding.
    """
    if old == new:
        return None, None
    oldp, newp = list(old.parameters.values()), list(new.parameters.values())
    names = {p.name for p in oldp if p.kind in (P.POSITIONAL_OR_KEYWORD, P.KEYWORD_ONLY)}
    if any(p.kind == P.VAR_KEYWORD for p in oldp):
        names |= {p.name for p in newp}
        sentinel = '__semver_extra'
        while sentinel in names:
            sentinel += '_'
        names.add(sentinel)
    names = sorted(names)
    if len(names) > 12:
        return None, 'call-domain comparison exceeds 12 keyword names'
    maxpos = max(sum(p.kind in (P.POSITIONAL_ONLY, P.POSITIONAL_OR_KEYWORD) for p in ps) for ps in (oldp, newp))
    if not any(p.kind == P.VAR_POSITIONAL for p in oldp):
        maxpos = sum(p.kind in (P.POSITIONAL_ONLY, P.POSITIONAL_OR_KEYWORD) for p in oldp)
    else:
        maxpos += 1
    for count in range(maxpos + 1):
        args = list(range(count))
        for size in range(len(names) + 1):
            for subset in itertools.combinations(names, size):
                kwargs = {name: 'value' for name in subset}
                try:
                    bind_call(old, args, kwargs)
                except TypeError:
                    continue
                try:
                    bind_call(new, args, kwargs)
                except TypeError as exc:
                    return {'args': args, 'kwargs': kwargs, 'reason': str(exc)}, None
    return None, None


def compare(old: Surface, new: Surface, old_version, new_version):
    bump, enforce = version_policy(old_version, new_version)
    findings, warnings = [], [f'before: {w}' for w in old.warnings] + [f'after: {w}' for w in new.warnings]

    def finding(path, rule, message, severity='breaking', witness=None):
        findings.append({'symbol': path, 'rule': rule, 'severity': severity, 'message': message,
                         'before': old.symbols[path].data(),
                         'after': new.symbols[path].data() if path in new.symbols else None,
                         'witness': witness})

    for path, a in sorted(old.symbols.items()):
        b = new.symbols.get(path)
        if b is None:
            finding(path, 'removed', 'Public symbol removed')
            continue
        if 'unresolved' in (a.kind, b.kind):
            warnings.append(f'{path}: unresolved API cannot be compared')
            continue
        if a.kind != b.kind:
            finding(path, 'kind-changed', f'{a.kind} became {b.kind}')
            continue
        if a.async_ != b.async_:
            finding(path, 'async-changed', 'Callable await contract changed')
        if a.binding != b.binding:
            finding(path, 'binding-changed', f'{a.binding} became {b.binding}')
        if a.signature is not None and b.signature is not None:
            witness, warning = rejected_call(a.signature, b.signature)
            if witness:
                finding(path, 'call-rejected', 'A previously valid call is rejected', witness=witness)
            if warning:
                warnings.append(f'{path}: {warning}')
            # Reordering named positional slots can silently change meaning.
            apos = [p for p in a.signature.parameters.values() if p.kind in (P.POSITIONAL_ONLY, P.POSITIONAL_OR_KEYWORD)]
            bpos = [p for p in b.signature.parameters.values() if p.kind in (P.POSITIONAL_ONLY, P.POSITIONAL_OR_KEYWORD)]
            for i, param in enumerate(apos):
                if param.kind == P.POSITIONAL_OR_KEYWORD and any(p.name == param.name for p in bpos) and bpos.index(next(p for p in bpos if p.name == param.name)) != i:
                    finding(path, 'positional-order', f'Positional slot for {param.name} changed')
                    break
            ad = {p.name: p.default for p in a.signature.parameters.values() if p.default != P.empty}
            bd = {p.name: p.default for p in b.signature.parameters.values() if p.default != P.empty}
            if any(name in bd and bd[name] != value for name, value in ad.items()):
                finding(path, 'default-changed', 'Default expression changed; review runtime behavior', 'review')
        elif a.signature != b.signature:
            warnings.append(f'{path}: constructor or callable signature unavailable')
        if a.annotation != b.annotation:
            finding(path, 'annotation-changed', 'Annotation changed; type compatibility not inferred', 'review')
    breaks = sum(f['severity'] == 'breaking' for f in findings)
    return {'schema_version': 1, 'versions': {'before': old_version, 'after': new_version, 'bump': bump},
            'policy': {'enforced': enforce, 'reason': 'stable minor/patch' if enforce else 'major or pre-1.0: no compatibility promise inferred'},
            'suspected_violation': bool(enforce and breaks),
            'analysis': 'partial' if warnings else 'static-subset',
            'summary': {'breaking': breaks, 'review': len(findings) - breaks,
                        'added': len(new.symbols.keys() - old.symbols.keys()),
                        'before_symbols': len(old.symbols), 'after_symbols': len(new.symbols)},
            'findings': findings, 'warnings': sorted(set(warnings)),
            'surfaces': {'before': {k: v.data() for k, v in sorted(old.symbols.items())},
                         'after': {k: v.data() for k, v in sorted(new.symbols.items())}}}
