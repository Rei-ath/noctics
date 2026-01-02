#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#if defined(__ARM_NEON) || defined(__ARM_NEON__)
#include <arm_neon.h>
#endif

typedef enum {
    KERNEL_SCALAR = 0,
    KERNEL_DOTPROD = 1,
    KERNEL_DOTPROD4 = 2,
    KERNEL_DOTPROD4I = 3,
} kernel_kind;

static void usage(const char *prog) {
    fprintf(stderr,
            "usage: %s [--n N] [--k K] [--iters I] [--kernel scalar|dotprod|dotprod4|dotprod4i] [--prefetch P] [--check] [--weights PATH]\n",
            prog);
}

static double now_sec(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

static size_t round_up16(size_t v) {
    return (v + 15u) & ~15u;
}

static void *aligned_alloc64(size_t size) {
    void *ptr = NULL;
    if (posix_memalign(&ptr, 64, size) != 0) {
        return NULL;
    }
    return ptr;
}

static uint64_t xorshift64(uint64_t *state) {
    uint64_t x = *state;
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    *state = x;
    return x;
}

static void fill_int8(int8_t *buf, size_t n, uint64_t seed) {
    for (size_t i = 0; i < n; i++) {
        seed = xorshift64(&seed);
        int8_t v = (int8_t)((seed >> 24) & 0x7f);
        if (seed & 1u) {
            v = (int8_t)-v;
        }
        buf[i] = v;
    }
}

static void pack_rows(const int8_t *w_in, int8_t *w_out, int n, int k, int k_padded) {
    for (int row = 0; row < n; row++) {
        const int8_t *src = w_in + (size_t)row * k;
        int8_t *dst = w_out + (size_t)row * k_padded;
        memcpy(dst, src, (size_t)k);
        if (k_padded > k) {
            memset(dst + k, 0, (size_t)(k_padded - k));
        }
    }
}

static void pack_rows4(const int8_t *w_in, int8_t *w_out, int n, int k, int k_padded) {
    int blocks = (n + 3) / 4;
    for (int b = 0; b < blocks; b++) {
        for (int r = 0; r < 4; r++) {
            int row = b * 4 + r;
            int8_t *dst = w_out + ((size_t)b * 4 + r) * (size_t)k_padded;
            if (row < n) {
                const int8_t *src = w_in + (size_t)row * k;
                memcpy(dst, src, (size_t)k);
                if (k_padded > k) {
                    memset(dst + k, 0, (size_t)(k_padded - k));
                }
            } else {
                memset(dst, 0, (size_t)k_padded);
            }
        }
    }
}

static void pack_rows4_interleaved(const int8_t *w_in, int8_t *w_out, int n, int k, int k_padded) {
    int blocks = (n + 3) / 4;
    int chunks = k_padded / 16;
    for (int b = 0; b < blocks; b++) {
        const int8_t *rows[4];
        for (int r = 0; r < 4; r++) {
            int row = b * 4 + r;
            if (row < n) {
                rows[r] = w_in + (size_t)row * k;
            } else {
                rows[r] = NULL;
            }
        }
        int8_t *dst = w_out + (size_t)b * 4 * k_padded;
        for (int c = 0; c < chunks; c++) {
            int col = c * 16;
            for (int r = 0; r < 4; r++) {
                int8_t *out = dst + col * 4 + r * 16;
                if (rows[r] && col < k) {
                    int available = k - col;
                    if (available >= 16) {
                        memcpy(out, rows[r] + col, 16);
                    } else {
                        memcpy(out, rows[r] + col, (size_t)available);
                        memset(out + available, 0, (size_t)(16 - available));
                    }
                } else {
                    memset(out, 0, 16);
                }
            }
        }
    }
}

static void gemv_scalar(const int8_t *w, const int8_t *x, int32_t *y, int n, int k_padded) {
    for (int row = 0; row < n; row++) {
        const int8_t *wrow = w + (size_t)row * k_padded;
        int32_t acc = 0;
        for (int j = 0; j < k_padded; j++) {
            acc += (int32_t)wrow[j] * (int32_t)x[j];
        }
        y[row] = acc;
    }
}

#if defined(__ARM_FEATURE_DOTPROD)
static inline void prefetch_ro(const void *ptr) {
    __builtin_prefetch(ptr, 0, 3);
}

static void gemv_dotprod(const int8_t *w, const int8_t *x, int32_t *y, int n, int k_padded, int prefetch_dist) {
    for (int row = 0; row < n; row++) {
        const int8_t *wrow = w + (size_t)row * k_padded;
        int32x4_t acc = vdupq_n_s32(0);
        for (int j = 0; j < k_padded; j += 16) {
            int pf = j + prefetch_dist * 16;
            if (prefetch_dist > 0 && pf < k_padded) {
                prefetch_ro(wrow + pf);
                prefetch_ro(x + pf);
            }
            int8x16_t vx = vld1q_s8(x + j);
            int8x16_t vw = vld1q_s8(wrow + j);
            acc = vdotq_s32(acc, vx, vw);
        }
        y[row] = vaddvq_s32(acc);
    }
}

static void gemv_dotprod4(const int8_t *w4, const int8_t *x, int32_t *y, int n, int k_padded, int prefetch_dist) {
    int blocks = (n + 3) / 4;
    for (int b = 0; b < blocks; b++) {
        const int8_t *base = w4 + (size_t)b * 4 * k_padded;
        const int8_t *w0 = base + (size_t)0 * k_padded;
        const int8_t *w1 = base + (size_t)1 * k_padded;
        const int8_t *w2 = base + (size_t)2 * k_padded;
        const int8_t *w3 = base + (size_t)3 * k_padded;
        int32x4_t acc0 = vdupq_n_s32(0);
        int32x4_t acc1 = vdupq_n_s32(0);
        int32x4_t acc2 = vdupq_n_s32(0);
        int32x4_t acc3 = vdupq_n_s32(0);
        for (int j = 0; j < k_padded; j += 16) {
            int pf = j + prefetch_dist * 16;
            if (prefetch_dist > 0 && pf < k_padded) {
                prefetch_ro(w0 + pf);
                prefetch_ro(w1 + pf);
                prefetch_ro(w2 + pf);
                prefetch_ro(w3 + pf);
                prefetch_ro(x + pf);
            }
            int8x16_t vx = vld1q_s8(x + j);
            acc0 = vdotq_s32(acc0, vx, vld1q_s8(w0 + j));
            acc1 = vdotq_s32(acc1, vx, vld1q_s8(w1 + j));
            acc2 = vdotq_s32(acc2, vx, vld1q_s8(w2 + j));
            acc3 = vdotq_s32(acc3, vx, vld1q_s8(w3 + j));
        }
        int row0 = b * 4 + 0;
        int row1 = b * 4 + 1;
        int row2 = b * 4 + 2;
        int row3 = b * 4 + 3;
        if (row0 < n) y[row0] = vaddvq_s32(acc0);
        if (row1 < n) y[row1] = vaddvq_s32(acc1);
        if (row2 < n) y[row2] = vaddvq_s32(acc2);
        if (row3 < n) y[row3] = vaddvq_s32(acc3);
    }
}

static void gemv_dotprod4_interleaved(const int8_t *w4i, const int8_t *x, int32_t *y, int n, int k_padded, int prefetch_dist) {
    int blocks = (n + 3) / 4;
    for (int b = 0; b < blocks; b++) {
        const int8_t *base = w4i + (size_t)b * 4 * k_padded;
        int32x4_t acc0 = vdupq_n_s32(0);
        int32x4_t acc1 = vdupq_n_s32(0);
        int32x4_t acc2 = vdupq_n_s32(0);
        int32x4_t acc3 = vdupq_n_s32(0);
        for (int j = 0; j < k_padded; j += 16) {
            int pf = j + prefetch_dist * 16;
            if (prefetch_dist > 0 && pf < k_padded) {
                prefetch_ro(base + pf * 4);
                prefetch_ro(x + pf);
            }
            const int8_t *blk = base + j * 4;
            int8x16_t vx = vld1q_s8(x + j);
            acc0 = vdotq_s32(acc0, vx, vld1q_s8(blk + 0));
            acc1 = vdotq_s32(acc1, vx, vld1q_s8(blk + 16));
            acc2 = vdotq_s32(acc2, vx, vld1q_s8(blk + 32));
            acc3 = vdotq_s32(acc3, vx, vld1q_s8(blk + 48));
        }
        int row0 = b * 4 + 0;
        int row1 = b * 4 + 1;
        int row2 = b * 4 + 2;
        int row3 = b * 4 + 3;
        if (row0 < n) y[row0] = vaddvq_s32(acc0);
        if (row1 < n) y[row1] = vaddvq_s32(acc1);
        if (row2 < n) y[row2] = vaddvq_s32(acc2);
        if (row3 < n) y[row3] = vaddvq_s32(acc3);
    }
}
#endif

static kernel_kind parse_kernel(const char *name) {
    if (strcmp(name, "scalar") == 0) return KERNEL_SCALAR;
    if (strcmp(name, "dotprod") == 0) return KERNEL_DOTPROD;
    if (strcmp(name, "dotprod4") == 0) return KERNEL_DOTPROD4;
    if (strcmp(name, "dotprod4i") == 0) return KERNEL_DOTPROD4I;
    return KERNEL_SCALAR;
}

static const char *kernel_name(kernel_kind k) {
    switch (k) {
        case KERNEL_SCALAR: return "scalar";
        case KERNEL_DOTPROD: return "dotprod";
        case KERNEL_DOTPROD4: return "dotprod4";
        case KERNEL_DOTPROD4I: return "dotprod4i";
        default: return "scalar";
    }
}

int main(int argc, char **argv) {
    int n = 1024;
    int k = 1024;
    int iters = 64;
    int prefetch_dist = 2;
    int check = 0;
    const char *weights_path = NULL;
    kernel_kind kernel = KERNEL_DOTPROD4;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--n") == 0 && i + 1 < argc) {
            n = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--k") == 0 && i + 1 < argc) {
            k = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--iters") == 0 && i + 1 < argc) {
            iters = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--kernel") == 0 && i + 1 < argc) {
            kernel = parse_kernel(argv[++i]);
        } else if (strcmp(argv[i], "--prefetch") == 0 && i + 1 < argc) {
            prefetch_dist = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--check") == 0) {
            check = 1;
        } else if (strcmp(argv[i], "--weights") == 0 && i + 1 < argc) {
            weights_path = argv[++i];
        } else if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0) {
            usage(argv[0]);
            return 0;
        } else {
            fprintf(stderr, "unknown arg: %s\n", argv[i]);
            usage(argv[0]);
            return 1;
        }
    }

    if (n <= 0 || k <= 0 || iters <= 0) {
        fprintf(stderr, "n, k, and iters must be > 0\n");
        return 1;
    }

    int k_padded = (int)round_up16((size_t)k);

    size_t w_in_bytes = (size_t)n * (size_t)k;
    size_t w_row_bytes = (size_t)n * (size_t)k_padded;
    size_t w4_bytes = (size_t)((n + 3) / 4) * 4u * (size_t)k_padded;

    int8_t *w_in = (int8_t *)aligned_alloc64(w_in_bytes);
    int8_t *w_rows = (int8_t *)aligned_alloc64(w_row_bytes);
    int8_t *w4 = (int8_t *)aligned_alloc64(w4_bytes);
    int8_t *w4i = (int8_t *)aligned_alloc64(w4_bytes);
    int8_t *x = (int8_t *)aligned_alloc64((size_t)k_padded);
    int32_t *y = (int32_t *)aligned_alloc64((size_t)n * sizeof(int32_t));
    int32_t *y_ref = (int32_t *)aligned_alloc64((size_t)n * sizeof(int32_t));

    if (!w_in || !w_rows || !w4 || !w4i || !x || !y || !y_ref) {
        fprintf(stderr, "alloc failed: %s\n", strerror(errno));
        return 1;
    }

    memset(x, 0, (size_t)k_padded);
    if (weights_path) {
        FILE *wf = fopen(weights_path, "rb");
        if (!wf) {
            fprintf(stderr, "failed to open weights: %s\n", strerror(errno));
            return 1;
        }
        size_t nread = fread(w_in, 1, w_in_bytes, wf);
        fclose(wf);
        if (nread != w_in_bytes) {
            fprintf(stderr, "weights size mismatch: expected %zu got %zu\n", w_in_bytes, nread);
            return 1;
        }
    } else {
        fill_int8(w_in, w_in_bytes, 0x1234ULL);
    }
    fill_int8(x, (size_t)k, 0x9abcULL);

    pack_rows(w_in, w_rows, n, k, k_padded);
    pack_rows4(w_in, w4, n, k, k_padded);
    pack_rows4_interleaved(w_in, w4i, n, k, k_padded);

    if (check) {
        gemv_scalar(w_rows, x, y_ref, n, k_padded);
    }

#if !defined(__ARM_FEATURE_DOTPROD)
    if (kernel == KERNEL_DOTPROD || kernel == KERNEL_DOTPROD4) {
        fprintf(stderr, "dotprod kernel requested but __ARM_FEATURE_DOTPROD is not available\n");
        return 1;
    }
#endif

    // Warmup
    gemv_scalar(w_rows, x, y, n, k_padded);

    double t0 = now_sec();
    for (int it = 0; it < iters; it++) {
        switch (kernel) {
            case KERNEL_SCALAR:
                gemv_scalar(w_rows, x, y, n, k_padded);
                break;
            case KERNEL_DOTPROD:
#if defined(__ARM_FEATURE_DOTPROD)
                gemv_dotprod(w_rows, x, y, n, k_padded, prefetch_dist);
#endif
                break;
            case KERNEL_DOTPROD4:
#if defined(__ARM_FEATURE_DOTPROD)
                gemv_dotprod4(w4, x, y, n, k_padded, prefetch_dist);
#endif
                break;
            case KERNEL_DOTPROD4I:
#if defined(__ARM_FEATURE_DOTPROD)
                gemv_dotprod4_interleaved(w4i, x, y, n, k_padded, prefetch_dist);
#endif
                break;
            default:
                gemv_scalar(w_rows, x, y, n, k_padded);
                break;
        }
    }
    double t1 = now_sec();

    if (check) {
        int mismatches = 0;
        int32_t max_diff = 0;
        for (int i = 0; i < n; i++) {
            int32_t diff = y[i] - y_ref[i];
            if (diff < 0) diff = -diff;
            if (diff > max_diff) max_diff = diff;
            if (diff != 0) {
                mismatches++;
                if (mismatches < 5) {
                    fprintf(stderr, "mismatch[%d]: got=%d ref=%d\n", i, y[i], y_ref[i]);
                }
            }
        }
        fprintf(stderr, "check: mismatches=%d max_abs_diff=%d\n", mismatches, max_diff);
    }

    double elapsed = t1 - t0;
    double per_iter = elapsed / (double)iters;

    double bytes_per_iter = (double)w_row_bytes + (double)k_padded + (double)n * sizeof(int32_t);
    double gbps = (bytes_per_iter * (double)iters) / (elapsed * 1e9);

    double ops = (double)n * (double)k * 2.0 * (double)iters;
    double gops = ops / (elapsed * 1e9);

    printf("kernel=%s n=%d k=%d k_padded=%d iters=%d prefetch=%d\n",
           kernel_name(kernel), n, k, k_padded, iters, prefetch_dist);
    printf("elapsed=%.6f s per_iter=%.6f s\n", elapsed, per_iter);
    printf("approx_gbps=%.3f approx_gops=%.3f\n", gbps, gops);
    printf("checksum=%" PRIu64 "\n", (uint64_t)y[0]);

    free(w_in);
    free(w_rows);
    free(w4);
    free(w4i);
    free(x);
    free(y);
    free(y_ref);

    return 0;
}
