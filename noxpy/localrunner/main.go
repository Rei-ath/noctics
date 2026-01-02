package main

import (
	"bufio"
	"errors"
	"flag"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/ollama/ollama/llama"
	"github.com/ollama/ollama/ml"
)

type runStats struct {
	PromptTokens    int
	GeneratedTokens int
	Prefill         time.Duration
	Generate        time.Duration
}

const metricsPrefix = "NR|"

type triBool struct {
	value bool
	set   bool
}

func (t *triBool) String() string {
	if t == nil {
		return "false"
	}
	return strconv.FormatBool(t.value)
}

func (t *triBool) Set(s string) error {
	val, err := strconv.ParseBool(s)
	if err != nil {
		return err
	}
	t.value = val
	t.set = true
	return nil
}

type streamWriter struct {
	writer     *bufio.Writer
	flushBytes int
	buffer     []byte
}

func newStreamWriter(writer *bufio.Writer, flushBytes int) *streamWriter {
	if flushBytes < 0 {
		flushBytes = 0
	}
	return &streamWriter{
		writer:     writer,
		flushBytes: flushBytes,
	}
}

func (s *streamWriter) WriteString(piece string) error {
	if s.flushBytes == 0 {
		if _, err := s.writer.WriteString(piece); err != nil {
			return err
		}
		return s.writer.Flush()
	}
	s.buffer = append(s.buffer, piece...)
	if len(s.buffer) >= s.flushBytes {
		if _, err := s.writer.Write(s.buffer); err != nil {
			return err
		}
		s.buffer = s.buffer[:0]
		return s.writer.Flush()
	}
	return nil
}

func (s *streamWriter) Flush() error {
	if len(s.buffer) > 0 {
		if _, err := s.writer.Write(s.buffer); err != nil {
			return err
		}
		s.buffer = s.buffer[:0]
	}
	return s.writer.Flush()
}

func main() {
	var (
		modelPath  = flag.String("model", "", "Path to the GGUF model (defaults to assets/models/nox.gguf)")
		maxTokens  = flag.Int("max-tokens", 128, "Maximum tokens to generate")
		ctxLength  = flag.Int("ctx", 1024, "Context length")
		batchSize  = flag.Int("batch", 32, "Batch size")
		temp       = flag.Float64("temp", 0.6, "Temperature")
		topP       = flag.Float64("top-p", 0.9, "Top-p")
		topK       = flag.Int("top-k", 40, "Top-k")
		repeatLast = flag.Int("repeat-last-n", 64, "Repetition window")
		repeatPen  = flag.Float64("repeat-penalty", 1.05, "Repetition penalty")
		fast       = flag.Bool("fast", false, "Fast/greedy sampling preset for lower latency")
		rawOut     = flag.Bool("raw", false, "Emit only generated tokens (no prefix/newlines)")
		prepack    = &triBool{}
		prefetch   = &triBool{}
		streamBuf  = flag.Int("stream-bytes", 0, "Buffer N bytes before flushing output (0 = flush each token)")
		kvWindow   = flag.Int("kv-window", 0, "Sliding KV window size (0 = disabled)")
		metrics    = flag.Bool("metrics", false, "Emit per-token logit metrics to stderr (NR|token|max|second|margin)")
		serve      = flag.Bool("serve", false, "Serve prompts from stdin (one per line)")
		serveRS    = flag.Bool("serve-rs", false, "Use ASCII record separator (0x1e) as prompt delimiter")
		keepCache  = flag.Bool("keep-cache", false, "Reuse KV cache between prompts when prefix matches")
		appendOnly = flag.Bool("append", false, "Append prompts onto existing cache (no reset)")
		inputOnly  = flag.Bool("input-only", false, "Keep KV cache aligned to prompt only (do not append generated tokens)")
		bench      = flag.Bool("bench", false, "Print benchmark stats to stderr")
		stateSave  = flag.String("state-save", "", "Save KV/cache state to a session file after each prompt")
		stateLoad  = flag.String("state-load", "", "Load KV/cache state from a session file before running")
		chatMode   = flag.Bool("chat", false, "Wrap prompts in a simple ChatML/Qwen-style chat format")
		systemMsg  = flag.String("system", "", "System prompt for -chat (default: minimal assistant)")
		cotMode    = flag.Bool("cot", false, "For -chat: request chain-of-thought style reasoning (more tokens, slower end-to-end)")
	)
	flag.Var(prepack, "prepack", "Preload+lock model weights in RAM (mlock) for faster inference")
	flag.Var(prefetch, "prefetch", "Warm OS cache by sequentially reading the model file")
	flag.Parse()

	if *fast {
		*temp = 0
		*topP = 1
		*topK = 1
		*repeatLast = 0
		*repeatPen = 1.0
	}

	var prompt string
	if !*serve {
		prompt = strings.TrimSpace(strings.Join(flag.Args(), " "))
		if prompt == "" {
			info, err := os.Stdin.Stat()
			if err == nil && info.Mode()&os.ModeCharDevice == 0 {
				// Read from stdin if piped
				in, _ := io.ReadAll(os.Stdin)
				prompt = strings.TrimSpace(string(in))
			}
		}
		if prompt == "" && *stateLoad == "" {
			fmt.Fprintln(os.Stderr, "provide a prompt via args or stdin")
			os.Exit(1)
		}
		if prompt == "" && *stateLoad != "" {
			fmt.Fprintln(os.Stderr, "provide a prompt or use -serve with -state-load")
			os.Exit(1)
		}
	}

	root, _ := os.Getwd()
	if *modelPath == "" {
		*modelPath = filepath.Join(root, "assets", "models", "nox.gguf")
	}
	threads := detectThreads()
	autoPrefetch, autoPrepack := autoWarmupFlags(*modelPath)
	prefetchOn := resolveTriBool(prefetch, "NOX_PREFETCH", autoPrefetch)
	prepackOn := resolveTriBool(prepack, "NOX_PREPACK", autoPrepack)

	defaultSystem := *systemMsg
	if defaultSystem == "" && (*chatMode || *cotMode) {
		defaultSystem = "You are nox. Be helpful, accurate, and concise."
	}
	if *cotMode {
		if defaultSystem != "" && !strings.HasSuffix(defaultSystem, "\n") {
			defaultSystem += "\n"
		}
		defaultSystem += "Think step by step and show your reasoning. End with a final short answer."
	}

	fmt.Fprintf(os.Stderr, "loading model: %s (threads=%d ctx=%d batch=%d)\n", *modelPath, threads, *ctxLength, *batchSize)
	if prepackOn {
		if llama.SupportsMlock() {
			fmt.Fprintln(os.Stderr, "prepack: mlock enabled")
		} else {
			fmt.Fprintln(os.Stderr, "prepack: mlock not supported on this device")
		}
	}
	if prefetchOn {
		if err := prefetchModel(*modelPath); err != nil {
			fmt.Fprintf(os.Stderr, "prefetch failed: %v\n", err)
		}
	}

	llama.BackendInit()

	model, err := llama.LoadModelFromFile(*modelPath, llama.ModelParams{
		UseMmap:  true,
		UseMlock: prepackOn,
		Progress: func(p float32) {
			// keep stderr quiet; uncomment for progress
			_ = p
		},
	})
	if err != nil {
		fmt.Fprintf(os.Stderr, "failed to load model: %v\n", err)
		os.Exit(1)
	}
	defer llama.FreeModel(model)

	ctxParams := llama.NewContextParams(*ctxLength, *batchSize, 1, threads, ml.FlashAttentionAuto, "")
	ctx, err := llama.NewContextWithModel(model, ctxParams)
	if err != nil {
		fmt.Fprintf(os.Stderr, "failed to create context: %v\n", err)
		os.Exit(1)
	}

	var loadedTokens []int
	if *stateLoad != "" {
		loadedTokens, err = ctx.StateLoadFile(*stateLoad, *ctxLength)
		if err != nil {
			fmt.Fprintf(os.Stderr, "failed to load state: %v\n", err)
			os.Exit(1)
		}
	}

	sampler, err := llama.NewSamplingContext(model, llama.SamplingParams{
		TopK:          *topK,
		TopP:          float32(*topP),
		Temp:          float32(*temp),
		RepeatLastN:   *repeatLast,
		PenaltyRepeat: float32(*repeatPen),
	})
	if err != nil {
		fmt.Fprintf(os.Stderr, "failed to create sampler: %v\n", err)
		os.Exit(1)
	}

	batch, err := llama.NewBatch(*batchSize, 1, 0)
	if err != nil {
		fmt.Fprintf(os.Stderr, "failed to allocate batch: %v\n", err)
		os.Exit(1)
	}
	defer batch.Free()

	appendFlag := *appendOnly
	keepFlag := *keepCache
	if len(loadedTokens) > 0 && !appendFlag && !keepFlag {
		appendFlag = true
	}

	writer := bufio.NewWriter(os.Stdout)
	streamer := newStreamWriter(writer, *streamBuf)
	if *serve {
		if *chatMode || *cotMode || *systemMsg != "" {
			fmt.Fprintln(os.Stderr, "note: -chat/-cot/-system are not applied in -serve mode")
		}
		if err := serveLoop(ctx, model, sampler, batch, streamer, *maxTokens, *rawOut, *serveRS, keepFlag, appendFlag, *inputOnly, *stateSave, loadedTokens, *kvWindow, *metrics); err != nil {
			fmt.Fprintf(os.Stderr, "serve loop failed: %v\n", err)
			os.Exit(1)
		}
		return
	}

	if *chatMode || *cotMode || *systemMsg != "" {
		prompt = buildChatMLPrompt(defaultSystem, prompt)
	}

	start := time.Now()
	var stats runStats
	var statsPtr *runStats
	if *bench {
		statsPtr = &stats
	}
	if len(loadedTokens) == 0 {
		if err := runPrompt(prompt, ctx, model, sampler, batch, streamer, *maxTokens, *rawOut, statsPtr, *stateSave, *kvWindow, *metrics); err != nil {
			fmt.Fprintf(os.Stderr, "inference failed: %v\n", err)
			os.Exit(1)
		}
	} else {
		toks, err := tokenizePrompt(model, prompt, true)
		if err != nil {
			fmt.Fprintf(os.Stderr, "tokenization failed: %v\n", err)
			os.Exit(1)
		}
		var saveFn func() error
		if *stateSave != "" {
			stateTokens := append(append([]int(nil), loadedTokens...), toks...)
			saveFn = func() error {
				return ctx.StateSaveFile(*stateSave, stateTokens)
			}
		}
		if _, err := runTokens(toks, 0, len(loadedTokens), ctx, model, sampler, batch, streamer, *maxTokens, *rawOut, statsPtr, saveFn, *kvWindow, *metrics); err != nil {
			fmt.Fprintf(os.Stderr, "inference failed: %v\n", err)
			os.Exit(1)
		}
		loadedTokens = append(loadedTokens, toks...)
	}
	if !*rawOut {
		streamer.Flush()
		fmt.Fprintln(writer)
		writer.Flush()
		fmt.Fprintf(os.Stderr, "\ncompleted in %s\n", time.Since(start).Round(time.Millisecond))
	}
	if *bench {
		total := stats.Prefill + stats.Generate
		tokPerSec := 0.0
		if stats.Generate > 0 {
			tokPerSec = float64(stats.GeneratedTokens) / stats.Generate.Seconds()
		}
		fmt.Fprintf(
			os.Stderr,
			"bench: prompt_tokens=%d generated_tokens=%d prefill_ms=%d gen_ms=%d total_ms=%d tok_s=%.2f\n",
			stats.PromptTokens,
			stats.GeneratedTokens,
			stats.Prefill.Milliseconds(),
			stats.Generate.Milliseconds(),
			total.Milliseconds(),
			tokPerSec,
		)
	}
}

func detectThreads() int {
	if v := os.Getenv("NOX_NUM_THREADS"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			return n
		}
	}
	return 4
}

func buildChatMLPrompt(system string, user string) string {
	// Minimal ChatML-like format supported by Qwen-style instruct models.
	// For other models this may work but is not guaranteed; use raw prompts if needed.
	user = strings.TrimSpace(user)
	if user == "" {
		return user
	}
	var sb strings.Builder
	if strings.TrimSpace(system) != "" {
		sb.WriteString("<|im_start|>system\n")
		sb.WriteString(strings.TrimSpace(system))
		sb.WriteString("\n<|im_end|>\n")
	}
	sb.WriteString("<|im_start|>user\n")
	sb.WriteString(user)
	sb.WriteString("\n<|im_end|>\n")
	sb.WriteString("<|im_start|>assistant\n")
	return sb.String()
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func serveLoop(ctx *llama.Context, model *llama.Model, sampler *llama.SamplingContext, batch *llama.Batch, writer *streamWriter, maxTokens int, rawOut bool, useRS bool, keepCache bool, appendOnly bool, inputOnly bool, stateSave string, initialTokens []int, kvWindow int, metrics bool) error {
	reader := bufio.NewReader(os.Stdin)
	endMarker := "\n<<<NOX_END>>>\n"
	if useRS {
		endMarker = string([]byte{0x1e})
	}

	prevTokens := append([]int(nil), initialTokens...)
	cacheGenerated := !inputOnly

	for {
		prompt, err := readPrompt(reader, useRS)
		if err == io.EOF {
			return nil
		}
		if err != nil {
			return err
		}
		if strings.TrimSpace(prompt) == "" {
			continue
		}
		if prompt == "exit" || prompt == "quit" {
			return nil
		}
		start := time.Now()
		toks, err := tokenizePrompt(model, prompt, appendOnly && len(prevTokens) > 0)
		if err != nil {
			fmt.Fprintf(os.Stderr, "tokenization failed: %v\n", err)
			continue
		}
		var generated []int
		var saveFn func() error
		if stateSave != "" {
			var stateTokens []int
			if appendOnly {
				stateTokens = append(append([]int(nil), prevTokens...), toks...)
			} else {
				stateTokens = toks
			}
			saveFn = func() error {
				return ctx.StateSaveFile(stateSave, stateTokens)
			}
		}
		if appendOnly {
			basePos := len(prevTokens)
			generated, err = runTokens(toks, 0, basePos, ctx, model, sampler, batch, writer, maxTokens, rawOut, nil, saveFn, kvWindow, metrics)
			prevTokens = append(prevTokens, toks...)
		} else if keepCache {
			common := commonPrefixLen(prevTokens, toks)
			if common == 0 {
				ctx.KvCacheClear()
			} else if common < len(prevTokens) {
				ctx.KvCacheSeqRm(0, common, -1)
			}
			generated, err = runTokens(toks, common, 0, ctx, model, sampler, batch, writer, maxTokens, rawOut, nil, saveFn, kvWindow, metrics)
			prevTokens = toks
		} else {
			generated, err = runTokens(toks, 0, 0, ctx, model, sampler, batch, writer, maxTokens, rawOut, nil, saveFn, kvWindow, metrics)
			prevTokens = toks
		}
		if err != nil {
			fmt.Fprintf(os.Stderr, "inference failed: %v\n", err)
		}
		if len(generated) > 0 && cacheGenerated && (appendOnly || keepCache) {
			prevTokens = append(prevTokens, generated...)
		} else if inputOnly && (appendOnly || keepCache) {
			if len(prevTokens) == 0 {
				ctx.KvCacheClear()
			} else {
				ctx.KvCacheSeqRm(0, len(prevTokens), -1)
			}
		}
		if kvWindow > 0 {
			prevTokens = trimTokens(prevTokens, kvWindow)
		}
		if !rawOut {
			writer.Flush()
			fmt.Fprintln(writer.writer)
		}
		fmt.Fprint(writer.writer, endMarker)
		writer.Flush()
		if !rawOut {
			fmt.Fprintf(os.Stderr, "\ncompleted in %s\n", time.Since(start).Round(time.Millisecond))
		}
	}
}

func readPrompt(reader *bufio.Reader, useRS bool) (string, error) {
	if useRS {
		data, err := reader.ReadBytes(0x1e)
		if err != nil && err != io.EOF {
			return "", err
		}
		if len(data) == 0 && err == io.EOF {
			return "", io.EOF
		}
		if len(data) > 0 && data[len(data)-1] == 0x1e {
			data = data[:len(data)-1]
		}
		return trimNewlines(string(data)), nil
	}

	line, err := reader.ReadString('\n')
	if err != nil && err != io.EOF {
		return "", err
	}
	if len(line) == 0 && err == io.EOF {
		return "", io.EOF
	}
	return trimNewlines(line), nil
}

func trimNewlines(s string) string {
	return strings.TrimRight(s, "\r\n")
}

func runPrompt(prompt string, ctx *llama.Context, model *llama.Model, sampler *llama.SamplingContext, batch *llama.Batch, writer *streamWriter, maxTokens int, rawOut bool, stats *runStats, stateSavePath string, kvWindow int, metrics bool) error {
	ctx.KvCacheClear()
	sampler.Reset()

	toks, err := tokenizePrompt(model, prompt, false)
	if err != nil {
		return err
	}
	if stats != nil {
		stats.PromptTokens = len(toks)
	}
	var saveFn func() error
	if stateSavePath != "" {
		saveFn = func() error {
			return ctx.StateSaveFile(stateSavePath, toks)
		}
	}
	_, err = runTokens(toks, 0, 0, ctx, model, sampler, batch, writer, maxTokens, rawOut, stats, saveFn, kvWindow, metrics)
	return err
}

func tokenizePrompt(model *llama.Model, prompt string, noBos bool) ([]int, error) {
	addSpecial := !noBos
	toks, err := model.Tokenize(prompt, addSpecial, true)
	if err != nil || len(toks) == 0 {
		if err == nil {
			err = fmt.Errorf("empty tokens")
		}
		return nil, err
	}
	return toks, nil
}

func runTokens(toks []int, startPos int, posOffset int, ctx *llama.Context, model *llama.Model, sampler *llama.SamplingContext, batch *llama.Batch, writer *streamWriter, maxTokens int, rawOut bool, stats *runStats, stateSave func() error, kvWindow int, metrics bool) ([]int, error) {
	if len(toks) == 0 {
		return nil, fmt.Errorf("empty tokens")
	}
	sampler.Reset()
	if startPos < 0 {
		startPos = 0
	}
	if startPos > len(toks) {
		startPos = len(toks)
	}

	if kvWindow > 0 && posOffset+len(toks) > kvWindow {
		return nil, fmt.Errorf("prompt tokens (%d) exceed kv-window (%d)", posOffset+len(toks), kvWindow)
	}

	prefillStart := time.Now()
	pos := startPos
	for pos < len(toks) {
		batch.Clear()
		chunk := min(len(toks)-pos, batch.Size())
		for i := 0; i < chunk; i++ {
			idx := pos + i
			absPos := posOffset + idx
			logits := idx == len(toks)-1
			batch.Add(toks[idx], nil, absPos, logits, 0)
		}
		if err := ctx.Decode(batch); err != nil {
			if errors.Is(err, llama.ErrKvCacheFull) {
				return nil, fmt.Errorf("kv cache full during prompt prefill (increase -ctx or reduce prompt length; or enable -kv-window for sliding context)")
			}
			return nil, fmt.Errorf("decode (prompt) failed: %v", err)
		}
		pos += chunk
	}
	if stats != nil {
		stats.Prefill = time.Since(prefillStart)
	}
	if stateSave != nil {
		if err := stateSave(); err != nil {
			return nil, err
		}
	}

	lastToken := toks[len(toks)-1]
	curPos := posOffset + len(toks)
	if !rawOut {
		fmt.Fprintln(writer.writer, "nox:")
	}

	generated := make([]int, 0, maxTokens)
	genStart := time.Now()
	for i := 0; i < maxTokens; i++ {
		if kvWindow > 0 && curPos >= kvWindow {
			curPos = shiftKvCache(ctx, curPos, kvWindow)
		}
		batch.Clear()
		batch.Add(lastToken, nil, curPos, true, 0)
		if err := ctx.Decode(batch); err != nil {
			if errors.Is(err, llama.ErrKvCacheFull) {
				if kvWindow > 0 {
					return generated, fmt.Errorf("kv cache full during generation (try increasing -ctx or -kv-window; current -kv-window=%d)", kvWindow)
				}
				return generated, fmt.Errorf("kv cache full during generation (increase -ctx or enable -kv-window for sliding context)")
			}
			return generated, fmt.Errorf("decode (gen) failed: %v", err)
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

		lastToken = token
		curPos++
	}
	if err := writer.Flush(); err != nil {
		return generated, err
	}
	if stats != nil {
		stats.GeneratedTokens = len(generated)
		stats.Generate = time.Since(genStart)
	}
	return generated, nil
}

func commonPrefixLen(a []int, b []int) int {
	n := len(a)
	if len(b) < n {
		n = len(b)
	}
	count := 0
	for i := 0; i < n; i++ {
		if a[i] != b[i] {
			break
		}
		count++
	}
	return count
}

func trimTokens(tokens []int, window int) []int {
	if window <= 0 || len(tokens) <= window {
		return tokens
	}
	return tokens[len(tokens)-window:]
}

func shiftKvCache(ctx *llama.Context, curPos int, window int) int {
	if window <= 0 || curPos < window {
		return curPos
	}
	if !ctx.KvCacheCanShift() {
		return curPos
	}
	discard := curPos - (window - 1)
	if discard <= 0 || discard >= curPos {
		return curPos
	}
	ctx.KvCacheSeqRm(0, 0, discard)
	ctx.KvCacheSeqAdd(0, discard, curPos, -discard)
	return curPos - discard
}

func envBool(name string) (bool, bool) {
	val, ok := os.LookupEnv(name)
	if !ok {
		return false, false
	}
	parsed, err := strconv.ParseBool(val)
	if err != nil {
		return false, false
	}
	return parsed, true
}

func resolveTriBool(flag *triBool, envKey string, auto bool) bool {
	if flag != nil && flag.set {
		return flag.value
	}
	if envKey != "" {
		if val, ok := envBool(envKey); ok {
			return val
		}
	}
	return auto
}

func autoWarmupFlags(modelPath string) (bool, bool) {
	const autoPrefetchMin = int64(1 << 30) // 1 GiB
	const autoPrepackMin = int64(1 << 30)  // 1 GiB
	info, err := os.Stat(modelPath)
	if err != nil {
		return false, false
	}
	size := info.Size()
	return size >= autoPrefetchMin, size >= autoPrepackMin
}

func prefetchModel(path string) error {
	file, err := os.Open(path)
	if err != nil {
		return err
	}
	defer file.Close()

	buf := make([]byte, 1<<20)
	_, err = io.CopyBuffer(io.Discard, file, buf)
	return err
}

func logitsTop2(ctx *llama.Context) (float32, float32) {
	logits := ctx.GetLogitsIth(-1)
	if len(logits) == 0 {
		return 0, 0
	}
	max1 := float32(math.Inf(-1))
	max2 := float32(math.Inf(-1))
	for _, v := range logits {
		if v > max1 {
			max2 = max1
			max1 = v
		} else if v > max2 {
			max2 = v
		}
	}
	return max1, max2
}
