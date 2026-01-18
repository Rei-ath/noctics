//go:build ignore
// +build ignore

// Experimental no-KV cache path extracted from runox.
// This file is excluded from builds. To re-enable, move the functions into
// `noxpy/runox/main.go` and wire the flag + call sites.

package main

import (
	"errors"
	"fmt"
	"os"
	"time"

	"github.com/ollama/ollama/llama"
)

// runTokensNoKV recomputes the full context for every generated token.
// It is intentionally slow and grows O(n^2) with output length.
func runTokensNoKV(toks []int, ctx *llama.Context, model *llama.Model, sampler *llama.SamplingContext, batch *llama.Batch, writer *streamWriter, maxTokens int, rawOut bool, stats *runStats, stateSave func() error, kvWindow int, metrics bool) ([]int, error) {
	if len(toks) == 0 {
		return nil, fmt.Errorf("empty tokens")
	}
	if kvWindow > 0 && len(toks) > kvWindow {
		toks = toks[len(toks)-kvWindow:]
	}
	if stats != nil {
		stats.PromptTokens = len(toks)
	}
	if !rawOut {
		fmt.Fprintln(writer.writer, "nox:")
	}

	logStamp("prefill_start")
	prefillStart := time.Now()
	if err := decodeSequence(ctx, batch, toks); err != nil {
		return nil, err
	}
	if stats != nil {
		stats.Prefill = time.Since(prefillStart)
	}
	logStamp("prefill_end")

	generated := make([]int, 0, maxTokens)
	genStart := time.Now()
	logStamp("gen_start")
	for i := 0; i < maxTokens; i++ {
		if i > 0 {
			ctx.KvCacheClear()
			seq := append([]int(nil), toks...)
			seq = append(seq, generated...)
			if kvWindow > 0 && len(seq) > kvWindow {
				seq = seq[len(seq)-kvWindow:]
			}
			logStampf("redecode_start idx=%d tokens=%d", i+1, len(seq))
			if err := decodeSequence(ctx, batch, seq); err != nil {
				return generated, err
			}
			logStampf("redecode_end idx=%d", i+1)
		}

		var max1 float32
		var max2 float32
		if metrics {
			max1, max2 = logitsTop2(ctx)
		}

		token := sampler.Sample(ctx, 0)
		sampler.Accept(token, true)
		if model.TokenIsEog(token) {
			break
		}
		generated = append(generated, token)
		piece := model.TokenToPiece(token)
		if err := writer.WriteString(piece); err != nil {
			return generated, err
		}
		if metrics {
			margin := max1 - max2
			fmt.Fprintf(os.Stderr, "%s%d|%.6f|%.6f|%.6f\n", metricsPrefix, token, max1, max2, margin)
		}
		logStampf("gen_token idx=%d id=%d", i+1, token)
	}
	if err := writer.Flush(); err != nil {
		return generated, err
	}
	if stats != nil {
		stats.GeneratedTokens = len(generated)
		stats.Generate = time.Since(genStart)
	}
	logStamp("gen_end")
	if stateSave != nil {
		if err := stateSave(); err != nil {
			return generated, err
		}
	}
	return generated, nil
}

func decodeSequence(ctx *llama.Context, batch *llama.Batch, seq []int) error {
	if len(seq) == 0 {
		return fmt.Errorf("empty tokens")
	}
	pos := 0
	last := len(seq) - 1
	for pos < last {
		batch.Clear()
		chunk := min(last-pos, batch.Size())
		for i := 0; i < chunk; i++ {
			idx := pos + i
			batch.Add(seq[idx], nil, idx, false, 0)
		}
		if err := ctx.Decode(batch); err != nil {
			if errors.Is(err, llama.ErrKvCacheFull) {
				return fmt.Errorf("kv cache full during no-kv decode (increase -ctx or reduce prompt length)")
			}
			return fmt.Errorf("decode (no-kv) failed: %v", err)
		}
		pos += chunk
		logStampf("decode_chunk pos=%d len=%d", pos, chunk)
	}
	batch.Clear()
	batch.Add(seq[last], nil, last, true, 0)
	if err := ctx.Decode(batch); err != nil {
		if errors.Is(err, llama.ErrKvCacheFull) {
			return fmt.Errorf("kv cache full during no-kv decode (increase -ctx or reduce prompt length)")
		}
		return fmt.Errorf("decode (no-kv) failed: %v", err)
	}
	logStamp("decode_last")
	return nil
}
