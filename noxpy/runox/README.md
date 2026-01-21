# Runox (local runner)

Runox is the local process runner that loads a GGUF model and streams tokens
over stdout. It is built from the Go sources in this folder and is used by
Noctics when a local runner is available.

## Build
From the repo root:

```sh
./scripts/build_runox.sh
```

Optional flags:

```sh
./scripts/build_runox.sh --dp        # dotprod build -> bin/runox_dp
./scripts/build_runox.sh --repack    # CPU repack kernels
./scripts/build_runox.sh --out /tmp/runox
```

## Run
From the repo root:

```sh
./bin/runox "hello"
```

You can also pass a prompt via stdin:

```sh
echo "hello" | ./bin/runox
```

## Common flags
```sh
./bin/runox -model assets/models/nox.gguf -max-tokens 128 -ctx 1024 -temp 0.6
```

Useful flags:
- `-model` path to GGUF (default: `assets/models/nox.gguf`)
- `-max-tokens` max generated tokens
- `-ctx` context length
- `-batch` batch size
- `-temp`, `-top-p`, `-top-k`
- `-serve` read one prompt per line from stdin
- `-serve-rs` use ASCII record separator (0x1e) as prompt delimiter
- `-raw` emit only tokens (no prefixes/newlines)

## Environment
- `NOX_NUM_THREADS` to override thread count
- `NOX_PREPACK=1` to mlock weights (if supported)
- `NOX_PREFETCH=1` to warm OS cache by reading the model file
