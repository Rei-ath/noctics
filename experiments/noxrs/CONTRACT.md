# NoxRS Contract (Frozen)

This file is the immutable spec for the current build. Any change requires
creating a new contract file; do not edit this in-place.

Spec
- Model: Mistral 7B Instruct v0.2
- Model file: mistral-7b-q4.gguf (GGUF V3, Q4_K)
- Context length: 1024
- Batch size: 1
- Decode: greedy (temp=0.0, top_p=1.0, top_k=1)
- Max new tokens: 128
- KV cache: FP16
- Device: CPU-only (no GPU dependency)
- I/O: stdin -> stdout, no HTTP

Success metrics (target device)
- TTFT <= 2.5s
- >= 2 tokens/sec steady-state
