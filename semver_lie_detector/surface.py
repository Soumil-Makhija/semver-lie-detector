"""Extract a declared Python API without importing or evaluating package code."""
import ast
from dataclasses import dataclass, field
import inspect
from pathlib import Path
import tokenize


@dataclass
class Symbol:
    kind: str
    signature: inspect.Signature | None = None
    async_: bool = False
    binding: str = "function"
    annotation: str | None = None
    location: str = ""

    def data(self):
        return {"kind": self.kind, "signature": str(self.signature) if self.signature else None,
                "async": self.async_, "binding": self.binding, "annotation": self.annotation,
                "location": self.location}


@dataclass
class Surface:
    symbols: dict[str, Symbol] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def signature(node, drop_first=False):
    a = node.args
    positional = a.posonlyargs + a.args
    defaults = [inspect.Parameter.empty] * (len(positional) - len(a.defaults))
    defaults += [ast.unparse(x) for x in a.defaults]
    params = []
    for i, (arg, default) in enumerate(zip(positional, defaults)):
        kind = inspect.Parameter.POSITIONAL_ONLY if i < len(a.posonlyargs) else inspect.Parameter.POSITIONAL_OR_KEYWORD
        params.append(inspect.Parameter(arg.arg, kind, default=default))
    if drop_first and params:
        params.pop(0)
    if a.vararg:
        params.append(inspect.Parameter(a.vararg.arg, inspect.Parameter.VAR_POSITIONAL))
    for arg, default in zip(a.kwonlyargs, a.kw_defaults):
        params.append(inspect.Parameter(arg.arg, inspect.Parameter.KEYWORD_ONLY,
                                       default=inspect.Parameter.empty if default is None else ast.unparse(default)))
    if a.kwarg:
        params.append(inspect.Parameter(a.kwarg.arg, inspect.Parameter.VAR_KEYWORD))
    return inspect.Signature(params)


def scan(root: Path) -> Surface:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"Not a source directory: {root}")
    # A package directory itself, or a parent containing packages/modules.
    base = root.parent if (root / '__init__.py').exists() else root
    result = Surface()
    modules = {}
    for path in sorted(root.rglob('*.py')):
        if any(p.startswith('.') or p == '__pycache__' for p in path.relative_to(root).parts):
            continue
        parts = list(path.relative_to(base).with_suffix('').parts)
        if parts[-1] == '__init__':
            parts.pop()
        if not parts:
            continue
        module = '.'.join(parts)
        try:
            with tokenize.open(path) as f:
                tree = ast.parse(f.read(), filename=str(path))
        except (SyntaxError, UnicodeError) as exc:
            result.warnings.append(f"{module}: parse failed: {exc}")
            continue
        modules[module] = (tree, path)
        result.symbols[module] = Symbol('module', location=str(path.relative_to(base)))
    if not modules:
        raise ValueError('No parseable public Python modules found; pass the import source root (often src/)')

    aliases = []
    exports = {}
    for module, (tree, path) in modules.items():
        loc = str(path.relative_to(base))
        declared = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '__all__' for t in node.targets):
                try:
                    value = ast.literal_eval(node.value)
                    if not isinstance(value, (list, tuple)) or not all(isinstance(x, str) for x in value):
                        raise ValueError()
                    declared = set(value)
                except (ValueError, TypeError):
                    result.warnings.append(f'{module}: dynamic __all__; export coverage incomplete')
            elif isinstance(node, (ast.AugAssign, ast.Expr)) and '__all__' in ast.unparse(node):
                result.warnings.append(f'{module}: modified __all__; export coverage incomplete')
        exports[module] = declared

        def public(name):
            return name in declared if declared is not None else not name.startswith('_')

        def add_nodes(nodes, prefix, in_class=False):
            for node in nodes:
                name = getattr(node, 'name', '')
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if (in_class and name not in ('__init__', '__call__') and name.startswith('_')) or (not in_class and not public(name)):
                        continue
                    decorators = [ast.unparse(d) for d in node.decorator_list]
                    known = {'staticmethod', 'classmethod', 'property'}
                    for d in decorators:
                        if d not in known:
                            result.warnings.append(f'{prefix}.{name}: decorator {d}; runtime signature may differ')
                    binding = 'static' if 'staticmethod' in decorators else 'class' if 'classmethod' in decorators else 'instance' if in_class else 'function'
                    sig = signature(node, drop_first=in_class and binding != 'static')
                    kind = 'property' if 'property' in decorators else 'function'
                    result.symbols[f'{prefix}.{name}'] = Symbol(kind, sig, isinstance(node, ast.AsyncFunctionDef), binding,
                                                               ast.unparse(node.returns) if node.returns else None, f'{loc}:{node.lineno}')
                    if in_class and name == '__init__':
                        result.symbols[prefix].signature = sig
                elif isinstance(node, ast.ClassDef) and (not name.startswith('_') if in_class else public(name)):
                    full = f'{prefix}.{name}'
                    result.symbols[full] = Symbol('class', location=f'{loc}:{node.lineno}')
                    if node.bases or node.keywords or node.decorator_list:
                        result.warnings.append(f'{full}: inheritance, metaclass or class decorators not resolved')
                    add_nodes(node.body, full, True)
                    if result.symbols[full].signature is None and not node.bases and not node.keywords and not node.decorator_list:
                        result.symbols[full].signature = inspect.Signature()
                elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        if isinstance(target, ast.Name) and (not target.id.startswith('_') if in_class else public(target.id)):
                            result.symbols[f'{prefix}.{target.id}'] = Symbol('attribute', annotation=ast.unparse(node.annotation) if isinstance(node, ast.AnnAssign) else None,
                                                                           location=f'{loc}:{node.lineno}')
                elif isinstance(node, ast.ImportFrom) and not in_class:
                    package = module.split('.') if path.name == '__init__.py' else module.split('.')[:-1]
                    source = '.'.join(package[:len(package) - node.level + 1] + ([node.module] if node.module else [])) if node.level else (node.module or '')
                    for item in node.names:
                        local = item.asname or item.name
                        if local == '*':
                            result.warnings.append(f'{module}: wildcard reexport from {source} unresolved')
                        elif public(local):
                            aliases.append((f'{module}.{local}', f'{source}.{item.name}', f'{loc}:{node.lineno}'))
                elif isinstance(node, ast.Import) and not in_class:
                    for item in node.names:
                        local = item.asname or item.name.split('.')[0]
                        if public(local):
                            aliases.append((f'{module}.{local}', item.name if item.asname else local, f'{loc}:{node.lineno}'))
                elif isinstance(node, (ast.If, ast.Try, ast.For, ast.While, ast.With, ast.Match)):
                    result.warnings.append(f'{prefix}:{node.lineno}: conditional declarations not resolved')
        add_nodes(tree.body, module)
        if any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == '__getattr__' for n in tree.body):
            result.warnings.append(f'{module}: dynamic __getattr__ exports not resolved')

    # Resolve internal reexports transitively, preserving alias member paths.
    pending = aliases
    for _ in range(len(aliases) + 1):
        remaining = []
        for dest, source, loc in pending:
            if source in result.symbols:
                for key, symbol in list(result.symbols.items()):
                    if key == source or key.startswith(source + '.'):
                        result.symbols[dest + key[len(source):]] = symbol
            else:
                remaining.append((dest, source, loc))
        if len(remaining) == len(pending):
            break
        pending = remaining
    for dest, source, loc in pending:
        result.symbols[dest] = Symbol('unresolved', location=loc)
        result.warnings.append(f'{dest}: unresolved import {source}')
    for module, names in exports.items():
        if names is not None:
            for name in sorted(names):
                if f'{module}.{name}' not in result.symbols:
                    result.warnings.append(f'{module}.{name}: declared export not resolved')
    result.symbols = {key: value for key, value in result.symbols.items()
                      if all(not part.startswith('_') or part in ('__init__', '__call__') for part in key.split('.'))}
    result.warnings = sorted(set(result.warnings))
    return result
