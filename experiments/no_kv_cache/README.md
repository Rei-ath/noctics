# No-KV Cache Experiment (Archived)

This experiment disabled KV caching by re-decoding the entire prompt + generated
history for every token. The result was slower and not worth keeping in the
production path.

The original implementation has been extracted to `no_kv_cache.go` and is
excluded from builds via a build tag. Use it only as a reference if you want
to retry the experiment later.

Summary (0.5B model, ctx=256, 2 tokens):
- With KV: ~29 tok/s
- No KV:   ~22 tok/s, and O(n^2) cost as tokens grow

