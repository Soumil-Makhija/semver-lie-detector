# Semver lie detector

A Python AST analyzer for suspected public API breaks in stable minor/patch releases.
Work in progress: the tested scanner and comparison library are implemented; CLI and PyPI acquisition are next.

Run the offline engine tests with Python 3.11+: `python -m unittest discover -s tests -v`.
The synthetic `examples/before` and `examples/after` include three incompatible changes.
Targets are parsed, never imported. This is static evidence, not a runtime compatibility guarantee.
