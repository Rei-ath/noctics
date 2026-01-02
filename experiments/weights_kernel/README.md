# weights_kernel (streamed weights micro-kernel)

Goal: prototype a weight-streaming linear-layer micro-kernel with explicit
prefetch and packed weights. This is an experiment only.

Build:
  ./build.sh

Run examples:
  ./build/weights_kernel --kernel scalar --n 512 --k 1024 --iters 64
  ./build/weights_kernel --kernel dotprod --n 1024 --k 1024 --iters 64 --prefetch 4
  ./build/weights_kernel --kernel dotprod4 --n 1024 --k 1024 --iters 64 --prefetch 4
  ./build/weights_kernel --kernel dotprod4i --n 1024 --k 1024 --iters 64 --prefetch 4
  ./gguf_extract_q8.py ../nox/obb/nox.gguf --tensor output.weight --rows 256 --cols 1024 --out /tmp/q8.bin
  ./build/weights_kernel --weights /tmp/q8.bin --n 256 --k 1024 --kernel dotprod4i --iters 64 --prefetch 4
  ./gguf_extract_q4k.py ../nox/obb/mistral-7b-q4.gguf --tensor blk.0.attn_q.weight --rows 256 --cols 1024 --out /tmp/q4k.bin
  ./build/weights_kernel --weights /tmp/q4k.bin --n 256 --k 1024 --kernel dotprod4i --iters 64 --prefetch 4
  ./build/gate_train --n 256 --k 1024 --samples 4 --block-k 32 --steps 25 --lr 1e-5 --lambda 1e-3 --threshold 0.6

Flags:
  --n N          output rows (default 1024)
  --k K          input size (default 1024)
  --iters I      benchmark iterations (default 64)
  --kernel KND   scalar | dotprod | dotprod4 | dotprod4i
  --prefetch P   prefetch distance in 16-byte blocks (default 2)
  --check        compare kernel output to scalar for a quick sanity check
  --weights PATH load int8 weights from a raw .bin file (size n*k bytes)

gguf_extract_q8.py notes:
- Only supports Q8_0 tensors.
- Extracts the raw int8 quant values and ignores per-block scale.
- Intended for bandwidth/packing experiments, not accuracy.

gguf_extract_q4k.py notes:
- Only supports Q4_K tensors.
- Expands 4-bit values to signed int8 (subtract 8) and ignores scales.
- Intended for bandwidth/packing experiments, not accuracy.

gate_train flags:
  --n N          output rows (default 256)
  --k K          input size (default 1024)
  --samples S    random input samples (default 4)
  --block-k B    size of gated K-blocks (default 32)
  --steps T      training steps (default 50)
  --lr LR        learning rate (default 1e-5)
  --lambda L     L1 penalty for sparsity (default 1e-3)
  --threshold P  gate threshold for final eval (default 0.5)

Notes:
- dotprod kernels require ARMv8.2-a+dotprod (build.sh sets -march).
- packing uses 4-row blocks for dotprod4 to reuse input vectors.
- throughput numbers are approximate; real memory traffic depends on cache.
