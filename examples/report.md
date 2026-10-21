# Static API compatibility report

1.0.0 → 1.1.0 (minor)

Suspected SemVer violation: **true**

Coverage: static-subset. 3 breaking findings; 0 changes to review; 0 added symbols.

Static evidence only. An empty finding list does not prove runtime compatibility.

| Symbol | Rule | Evidence |
| --- | --- | --- |
| demo.Client.send | breaking: call-rejected | A previously valid call is rejected — {"args": [], "kwargs": {"message": "value"}, "reason": "missing a required argument: 'timeout'"} |
| demo.LEGACY | breaking: removed | Public symbol removed |
| demo.greet | breaking: call-rejected | A previously valid call is rejected — {"args": [0, 1], "kwargs": {}, "reason": "too many positional arguments"} |
