#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef struct {
    int n;
    int k;
    int samples;
    int block_k;
    int steps;
    float lr;
    float lambda;
    float threshold;
} train_cfg;

static double now_sec(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
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

static void gemv_dense(const int8_t *w, const int8_t *x, int32_t *y, int n, int k) {
    for (int row = 0; row < n; row++) {
        const int8_t *wrow = w + (size_t)row * k;
        int32_t acc = 0;
        for (int j = 0; j < k; j++) {
            acc += (int32_t)wrow[j] * (int32_t)x[j];
        }
        y[row] = acc;
    }
}

static void gemv_block(const int8_t *w, const int8_t *x, int32_t *out, int n, int k, int k0, int k1) {
    for (int row = 0; row < n; row++) {
        const int8_t *wrow = w + (size_t)row * k;
        int32_t acc = 0;
        for (int j = k0; j < k1; j++) {
            acc += (int32_t)wrow[j] * (int32_t)x[j];
        }
        out[row] = acc;
    }
}

static float l2_error(const int32_t *a, const int32_t *b, int n) {
    double sum = 0.0;
    for (int i = 0; i < n; i++) {
        double d = (double)a[i] - (double)b[i];
        sum += d * d;
    }
    return (float)(sum / (double)n);
}

static void usage(const char *prog) {
    fprintf(stderr,
            "usage: %s [--n N] [--k K] [--samples S] [--block-k B] [--steps T] [--lr LR] [--lambda L] [--threshold P]\n",
            prog);
}

static int parse_args(train_cfg *cfg, int argc, char **argv) {
    cfg->n = 256;
    cfg->k = 1024;
    cfg->samples = 4;
    cfg->block_k = 32;
    cfg->steps = 50;
    cfg->lr = 1e-5f;
    cfg->lambda = 1e-3f;
    cfg->threshold = 0.5f;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--n") == 0 && i + 1 < argc) {
            cfg->n = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--k") == 0 && i + 1 < argc) {
            cfg->k = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--samples") == 0 && i + 1 < argc) {
            cfg->samples = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--block-k") == 0 && i + 1 < argc) {
            cfg->block_k = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--steps") == 0 && i + 1 < argc) {
            cfg->steps = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--lr") == 0 && i + 1 < argc) {
            cfg->lr = (float)atof(argv[++i]);
        } else if (strcmp(argv[i], "--lambda") == 0 && i + 1 < argc) {
            cfg->lambda = (float)atof(argv[++i]);
        } else if (strcmp(argv[i], "--threshold") == 0 && i + 1 < argc) {
            cfg->threshold = (float)atof(argv[++i]);
        } else if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0) {
            usage(argv[0]);
            return 1;
        } else {
            fprintf(stderr, "unknown arg: %s\n", argv[i]);
            usage(argv[0]);
            return 1;
        }
    }
    if (cfg->n <= 0 || cfg->k <= 0 || cfg->samples <= 0 || cfg->block_k <= 0 || cfg->steps <= 0) {
        fprintf(stderr, "invalid args\n");
        return 1;
    }
    return 0;
}

int main(int argc, char **argv) {
    train_cfg cfg;
    if (parse_args(&cfg, argc, argv) != 0) {
        return 1;
    }

    int blocks = (cfg.k + cfg.block_k - 1) / cfg.block_k;

    size_t w_bytes = (size_t)cfg.n * (size_t)cfg.k;
    size_t x_bytes = (size_t)cfg.samples * (size_t)cfg.k;
    size_t y_bytes = (size_t)cfg.samples * (size_t)cfg.n * sizeof(int32_t);

    int8_t *w = (int8_t *)aligned_alloc64(w_bytes);
    int8_t *x = (int8_t *)aligned_alloc64(x_bytes);
    int32_t *y_dense = (int32_t *)aligned_alloc64(y_bytes);
    int32_t *y_pred = (int32_t *)aligned_alloc64((size_t)cfg.n * sizeof(int32_t));
    int32_t *c_block = (int32_t *)aligned_alloc64((size_t)cfg.n * sizeof(int32_t));
    float *g = (float *)aligned_alloc64((size_t)blocks * sizeof(float));
    float *grad = (float *)aligned_alloc64((size_t)blocks * sizeof(float));

    if (!w || !x || !y_dense || !y_pred || !c_block || !g || !grad) {
        fprintf(stderr, "alloc failed: %s\n", strerror(errno));
        return 1;
    }

    fill_int8(w, w_bytes, 0x1234ULL);
    fill_int8(x, x_bytes, 0x9abcULL);

    for (int s = 0; s < cfg.samples; s++) {
        gemv_dense(w, x + (size_t)s * cfg.k, y_dense + (size_t)s * cfg.n, cfg.n, cfg.k);
    }

    for (int b = 0; b < blocks; b++) {
        g[b] = 1.0f;
    }

    double t0 = now_sec();
    for (int step = 0; step < cfg.steps; step++) {
        for (int b = 0; b < blocks; b++) {
            grad[b] = 0.0f;
        }

        double loss = 0.0;
        for (int s = 0; s < cfg.samples; s++) {
            memset(y_pred, 0, (size_t)cfg.n * sizeof(int32_t));
            const int8_t *xs = x + (size_t)s * cfg.k;
            const int32_t *yd = y_dense + (size_t)s * cfg.n;

            for (int b = 0; b < blocks; b++) {
                int k0 = b * cfg.block_k;
                int k1 = k0 + cfg.block_k;
                if (k1 > cfg.k) k1 = cfg.k;
                gemv_block(w, xs, c_block, cfg.n, cfg.k, k0, k1);
                float gb = g[b];
                for (int i = 0; i < cfg.n; i++) {
                    y_pred[i] += (int32_t)(gb * (float)c_block[i]);
                }
            }

            double sample_loss = 0.0;
            for (int i = 0; i < cfg.n; i++) {
                double d = (double)y_pred[i] - (double)yd[i];
                sample_loss += d * d;
            }
            loss += 0.5 * sample_loss;

            for (int b = 0; b < blocks; b++) {
                int k0 = b * cfg.block_k;
                int k1 = k0 + cfg.block_k;
                if (k1 > cfg.k) k1 = cfg.k;
                gemv_block(w, xs, c_block, cfg.n, cfg.k, k0, k1);
                double dot = 0.0;
                for (int i = 0; i < cfg.n; i++) {
                    double err = (double)y_pred[i] - (double)yd[i];
                    dot += err * (double)c_block[i];
                }
                grad[b] += (float)dot;
            }
        }

        for (int b = 0; b < blocks; b++) {
            float gnew = g[b] - cfg.lr * (grad[b] / (float)cfg.samples + cfg.lambda);
            if (gnew < 0.0f) gnew = 0.0f;
            if (gnew > 1.0f) gnew = 1.0f;
            g[b] = gnew;
        }

        int active = 0;
        float gsum = 0.0f;
        for (int b = 0; b < blocks; b++) {
            gsum += g[b];
            if (g[b] >= cfg.threshold) {
                active++;
            }
        }

        printf("step=%d loss=%.3e avg_g=%.3f active=%d/%d\n",
               step + 1, loss / (double)cfg.samples, gsum / (float)blocks, active, blocks);
    }
    double t1 = now_sec();

    // Final evaluation with thresholded gates
    int active = 0;
    for (int b = 0; b < blocks; b++) {
        if (g[b] >= cfg.threshold) {
            active++;
        }
    }

    double eval_loss = 0.0;
    for (int s = 0; s < cfg.samples; s++) {
        memset(y_pred, 0, (size_t)cfg.n * sizeof(int32_t));
        const int8_t *xs = x + (size_t)s * cfg.k;
        const int32_t *yd = y_dense + (size_t)s * cfg.n;
        for (int b = 0; b < blocks; b++) {
            if (g[b] < cfg.threshold) {
                continue;
            }
            int k0 = b * cfg.block_k;
            int k1 = k0 + cfg.block_k;
            if (k1 > cfg.k) k1 = cfg.k;
            gemv_block(w, xs, c_block, cfg.n, cfg.k, k0, k1);
            for (int i = 0; i < cfg.n; i++) {
                y_pred[i] += c_block[i];
            }
        }
        eval_loss += l2_error(y_pred, yd, cfg.n);
    }
    eval_loss /= (double)cfg.samples;

    printf("final: active=%d/%d (%.1f%%) eval_mse=%.3e train_time=%.2fs\n",
           active, blocks, 100.0 * (double)active / (double)blocks, eval_loss, t1 - t0);

    free(w);
    free(x);
    free(y_dense);
    free(y_pred);
    free(c_block);
    free(g);
    free(grad);

    return 0;
}
