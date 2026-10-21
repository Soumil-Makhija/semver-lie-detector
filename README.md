# Semver lie detector

Find **suspected Python public API breaks** in a release labeled minor or patch.
Parse source with Python's AST, compare exported symbols and callable argument
domains, and export deterministic JSON or shareable Markdown. Target packages are
never installed, imported, or built.

## Try it offline

Python 3.11+; no runtime dependencies. From this checkout:

```sh
python -m semver_lie_detector local examples/before examples/after \
  --before-version 1.0.0 --after-version 1.1.0 --format markdown
```

This intentionally exits **1** and reports three breaks: `demo.LEGACY` was removed,
`greet` no longer accepts its second positional argument, and `Client.send` now
requires `timeout`. Each rejected signature includes concrete `args`/`kwargs` that
bind to the old version and fail against the new version.

Install the console command in an isolated environment:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install .
semver-lie --help
```

Installation downloads the setuptools build backend. Running directly from the
checkout with `python -m semver_lie_detector` works without that download.

## Compare PyPI releases

```sh
semver-lie pypi click --module click \
  --before-version 8.1.6 --after-version 8.1.7 \
  --output click-report.json
```

`--module` is the actual top-level Python import name, which can differ from the
PyPI project name. This command fetches PyPI JSON metadata, verifies that the two
versions are consecutive **among stable, three-component releases with artifacts**
(including yanked releases), downloads their sdists, checks SHA256 against PyPI,
and scans only the selected module/package. It does not execute setup.py or any
package code. Network errors produce exit 2. Unsupported versions/layouts fail
explicitly; no wheel/build fallback runs silently.

The report records artifact URLs, hashes and yanked status. Checksums verify
consistency with PyPI metadata, not author identity or that code is safe to run.
Only HTTPS PyPI/pythonhosted URLs are accepted. Downloads are capped at 20 MiB;
expanded archives at 50 MiB and 10,000 members. Only regular `.py` files are copied;
links, traversal paths, duplicate sources and special files are rejected.

For local checkouts, pass the import root (`src/` for many projects), a package
folder containing `__init__.py`, or one `.py` module. Both sides must describe the
same import namespace. Local mode trusts the supplied versions and does not
verify release adjacency.

## Findings and exit codes

| Code | Meaning |
| --- | --- |
| 0 | No suspected stable minor/patch violation in the analyzed subset |
| 1 | At least one breaking finding under stable minor/patch policy |
| 2 | Invalid inputs, acquisition, parsing or output failure |
| 3 | Partial coverage with `--fail-on-partial`, when no violation takes priority |

Major releases and pre-1.0 versions still get findings, but are not called SemVer
violations. Stable `MAJOR.MINOR.PATCH` is required; local mode also permits build
metadata. PEP 440 prereleases, epochs, post/dev releases, two-component versions
and general PEP 440 release ordering are outside this policy. This tool assumes a
SemVer contract; a package may explicitly use another versioning policy.

Rules cover public symbol/module removal, symbol kind, async and descriptor binding
changes, reordered named positional slots, and calls accepted before but rejected
after. Required/optional parameters, positional-only and keyword-only arguments,
`*args`, and `**kwargs` participate. Defaults and return/data annotations generate
review findings, not claims of behavioral/type incompatibility.

JSON schema version 1 contains versions and policy, summary, findings, witness
calls, before/after locations and signatures, coverage warnings, full scanned
surfaces, acquisition provenance and release-order semantics. Keys and findings
are sorted and timestamps/temporary absolute paths are omitted for reproducibility.
`--format markdown --output report.md` gives a human-readable report.

## Architecture and supported public API

1. `surface.py` parses `.py` files with stdlib `ast` and builds a source-located API.
2. Literal `__all__` controls module exports; otherwise non-underscore declarations
   are public. Public submodules are analyzed independently. Local imports and
   reexports are resolved transitively, including exports from private modules.
3. `compare.py` compares symbol contracts and enumerates binding equivalence
   classes: relevant keyword subsets and positional counts up to the largest
   declared positional arity plus one variadic overflow case. It does not choose
   random calls. More than 12 relevant keyword names on a changed signature yields
   an explicit coverage warning; identical signatures need no enumeration.
4. `pypi.py` acquires bounded verified sources; `cli.py` applies version policy and
   renders shareable evidence. All target expressions remain inert source strings.

## Limitations

An empty report **does not prove compatibility**. Python permits dynamic APIs and
behavior changes that source signatures cannot establish. `analysis: partial`
means coverage warnings exist; `static-subset` means the declared subset was
analyzed, not that the whole runtime API is verified. Use `--fail-on-partial` for a
stricter CI policy. A partial report can contain both useful evidence and false
positives from unresolved constructs; inspect warnings and source before acting.

- Inheritance/metaclasses, arbitrary decorators, conditional declarations,
  wildcard/external reexports, dynamic `__all__` and module `__getattr__` are
  unresolved and produce warnings. Renamed private declarations may remain
  unresolved. Property setters/custom descriptors and overloaded signatures are
  not fully modeled. Constructor signatures use a declared `__init__` or the
  default empty constructor for a plain class; inherited constructors are unknown.
- Assignment aliases, generated exports, instance attributes, monkey patches,
  native/Cython APIs, `.pyi` stubs, argument type compatibility, exceptions, runtime
  semantics and dependency changes are outside the model. Function parameter
  annotations are not compared. Annotation findings cover returns and annotated
  attributes only. Value/default changes require human review.
- A `.py` source distribution may differ from a published wheel. Remote acquisition
  supports regular packages/single modules at the sdist root, `src/`, or `lib/`.
  Namespace and custom layouts require local mode with an appropriate import root.
- Parse failures are coverage warnings when other modules can be scanned, and an
  error if no public module can be parsed. Paths are relative to the import root.
- There is no npm analyzer or offender dashboard. The project implements the
  queue's PyPI option. Results are evidence for review, not accusations of intent.

## Validation

```sh
python -m unittest discover -s tests -v
python -m compileall -q semver_lie_detector
```

Tests cover call compatibility and real binding witnesses, exports, methods,
constructors, static/async contracts, policy boundaries, deterministic CLI output,
coverage signaling, no target execution, safe archive extraction, hashes and
mocked offline PyPI integration. GitHub Actions also installs and smoke-tests the
CLI on Python 3.11–3.14. Live PyPI access is an explicit integration check, not a
network dependency of the offline suite.

## References

- [Python AST](https://docs.python.org/3/library/ast.html)
- [PyPI JSON API](https://docs.pypi.org/api/json/)
- [Semantic Versioning 2.0.0](https://semver.org/)

MIT licensed.
