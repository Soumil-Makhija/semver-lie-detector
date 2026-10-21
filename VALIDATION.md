# Validation evidence

Measured during the 2026-10-21 build session. No package compatibility conclusion
below extends beyond the documented static subset.

## Offline acceptance

```sh
python -m unittest discover -s tests -v
python -m compileall -q semver_lie_detector
git diff --check
```

20 test methods pass locally on Python 3.14.2. The runtime-oracle method compares
all 225 ordered pairs of 15 fixed synthetic function signatures against actual
Python calls, testing positional counts 0–3 and all subsets of `x`, `y`, `extra`.
It also executes each predicted witness against both synthetic functions to check
that the old function accepts it and the new function rejects it. Only hardcoded
test functions execute; target-package source never executes.

The offline example reports exactly three breaking findings and exits 1:

```sh
python -m semver_lie_detector local examples/before examples/after \
  --before-version 1.0.0 --after-version 1.1.0 --format markdown
```

See [the generated report](examples/report.md). Other tests cover nonbreaking
extensions, version-policy boundaries, local reexports, methods, constructor
signatures, async changes, review findings, partial coverage, deterministic
serialization, CLI subprocess behavior, checksum mismatch, traversal/link and
expanded-size rejection, and mocked PyPI integration.

The initial Python 3.11 CI run caught `inspect.Signature.bind` behavior that differed
from local 3.14 for defaulted positional-only parameters combined with `**kwargs`.
The analyzer now normalizes positional-only names before binding; a real runtime
regression test checks this case. The replacement CI passed on Python 3.11–3.14:
https://github.com/Soumil-Makhija/semver-lie-detector/actions/runs/39674501740
The latest commit's workflow remains the authoritative final validation status.

## Live PyPI integration

```sh
python -m semver_lie_detector pypi click --module click \
  --before-version 8.1.6 --after-version 8.1.7 --output click-report.json
```

Observed exit 0. Release adjacency among stable three-component releases was
verified. Both downloaded source archives matched their published PyPI SHA256.
Each scanned surface contains 1,207 symbols: zero breaking/review findings and
zero added symbols. **Coverage is partial, with 380 warnings**, mainly unresolved
inheritance, decorators and external imports. This is not proof of compatibility
and does not identify Click as an offender. With `--fail-on-partial`, this report
would exit 3. [The compact measured summary](examples/validation/click-8.1.6-8.1.7.json)
records artifact URLs, hashes, policy and warning examples. Reproducing requires
network access to PyPI; package metadata may change over time.

## Packaging

A project-local clean virtual environment successfully built and installed the
wheel using `python -m pip install --no-deps .`. The installed `semver-lie --help`
and the offline console-command example were smoke-tested. CI repeats installation
and the three-break example on every supported Python version. There are no
runtime dependencies or paid/model service requirements.
