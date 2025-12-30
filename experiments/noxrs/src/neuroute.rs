use std::cmp::Ordering;

use crate::routing_weights;

const EPS: f32 = 1e-6;

#[allow(dead_code)]
pub struct RouteResult {
    pub probs: Vec<f32>,
    pub mask: Vec<bool>,
    pub perm: Vec<usize>,
}

pub fn route_values(values: &[f32]) -> RouteResult {
    let feats = build_features(values);
    let probs = predict_proba(&feats);
    let (mask, perm) = pick_mask(values, &probs);
    RouteResult { probs, mask, perm }
}

fn build_features(values: &[f32]) -> Vec<[f32; 8]> {
    let n = values.len();
    let n_f = n as f32;
    let pos_den = if n > 1 { (n - 1) as f32 } else { 1.0 };
    let mean = values.iter().sum::<f32>() / n_f;
    let mut var = 0.0_f32;
    for v in values {
        let d = v - mean;
        var += d * d;
    }
    let std = (var / n_f).sqrt() + EPS;

    let mut order: Vec<usize> = (0..n).collect();
    order.sort_by(|&a, &b| {
        values[a]
            .partial_cmp(&values[b])
            .unwrap_or(Ordering::Equal)
            .then_with(|| a.cmp(&b))
    });
    let mut ranks = vec![0usize; n];
    for (rank, idx) in order.iter().enumerate() {
        ranks[*idx] = rank;
    }

    let mut feats = Vec::with_capacity(n);
    for (i, &v) in values.iter().enumerate() {
        let pos_norm = i as f32 / pos_den;
        let centered = v - mean;
        let zscore = centered / std;
        let rank_norm = ranks[i] as f32 / pos_den;
        let cdf = (ranks[i] as f32 + 0.5) / n_f;
        feats.push([
            v,
            pos_norm,
            mean,
            std,
            centered,
            zscore,
            rank_norm,
            cdf,
        ]);
    }
    feats
}

fn predict_proba(feats: &[[f32; 8]]) -> Vec<f32> {
    let mut probs = Vec::with_capacity(feats.len());
    for feat in feats {
        let mut hidden = [0.0_f32; routing_weights::HIDDEN];
        for h in 0..routing_weights::HIDDEN {
            let mut acc = routing_weights::B1[h];
            for i in 0..routing_weights::IN_DIM {
                let w = routing_weights::W1[i * routing_weights::HIDDEN + h];
                acc += feat[i] * w;
            }
            hidden[h] = acc.max(0.0);
        }
        let mut logit = routing_weights::B2;
        for h in 0..routing_weights::HIDDEN {
            logit += hidden[h] * routing_weights::W2[h];
        }
        probs.push(sigmoid(logit));
    }
    probs
}

fn sigmoid(x: f32) -> f32 {
    let x = x.clamp(-50.0, 50.0);
    1.0 / (1.0 + (-x).exp())
}

fn mask_log_likelihood(mask: &[bool], probs: &[f32]) -> f32 {
    let mut score = 0.0_f32;
    for (m, p) in mask.iter().zip(probs.iter()) {
        let p = p.clamp(1e-9, 1.0 - 1e-9);
        if *m {
            score += p.ln();
        } else {
            score += (1.0 - p).ln();
        }
    }
    score
}

fn pick_mask(values: &[f32], probs: &[f32]) -> (Vec<bool>, Vec<usize>) {
    let n = values.len();
    let mask_thr: Vec<bool> = probs.iter().map(|p| *p >= 0.5).collect();
    let mut mask_topk = vec![false; n];

    let mut order: Vec<usize> = (0..n).collect();
    order.sort_by(|&a, &b| {
        probs[b]
            .partial_cmp(&probs[a])
            .unwrap_or(Ordering::Equal)
            .then_with(|| a.cmp(&b))
    });
    let mut k_hat = probs.iter().sum::<f32>().round() as i32;
    k_hat = k_hat.clamp(0, n as i32);
    for idx in order.iter().take(k_hat as usize) {
        mask_topk[*idx] = true;
    }

    let mut best_mask = mask_thr.clone();
    let best_score = mask_log_likelihood(&best_mask, probs);
    let score_topk = mask_log_likelihood(&mask_topk, probs);
    if score_topk > best_score {
        best_mask = mask_topk;
    }

    let perm = stable_partition(&best_mask);
    if perm.len() != n {
        let perm = canonical_partition(values, Some(probs));
        let mask = partition_mask(n, &perm);
        return (mask, perm);
    }
    (best_mask, perm)
}

fn stable_partition(mask: &[bool]) -> Vec<usize> {
    let mut perm = Vec::with_capacity(mask.len());
    for (idx, m) in mask.iter().enumerate() {
        if *m {
            perm.push(idx);
        }
    }
    for (idx, m) in mask.iter().enumerate() {
        if !*m {
            perm.push(idx);
        }
    }
    perm
}

fn canonical_partition(values: &[f32], probs: Option<&[f32]>) -> Vec<usize> {
    let n = values.len();
    let mut mask = vec![false; n];
    if let Some(probs) = probs {
        let mut order: Vec<usize> = (0..n).collect();
        order.sort_by(|&a, &b| {
            probs[b]
                .partial_cmp(&probs[a])
                .unwrap_or(Ordering::Equal)
                .then_with(|| a.cmp(&b))
        });
        let mut k_hat = probs.iter().sum::<f32>().round() as i32;
        k_hat = k_hat.clamp(0, n as i32);
        if k_hat > 0 {
            for idx in order.iter().take(k_hat as usize) {
                mask[*idx] = true;
            }
        }
    } else if n > 0 {
        let mut sorted = values.to_vec();
        sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(Ordering::Equal));
        let median = quantile(&sorted, 0.5);
        for (i, v) in values.iter().enumerate() {
            if *v >= median {
                mask[i] = true;
            }
        }
    }
    if mask.iter().all(|m| !*m) {
        if let Some((idx, _)) = values
            .iter()
            .enumerate()
            .max_by(|a, b| a.1.partial_cmp(b.1).unwrap_or(Ordering::Equal))
        {
            mask[idx] = true;
        }
    }
    stable_partition(&mask)
}

fn partition_mask(n: usize, perm: &[usize]) -> Vec<bool> {
    let mut seen = vec![false; n];
    for idx in perm {
        if *idx < n {
            seen[*idx] = true;
        }
    }
    seen
}

fn quantile(sorted: &[f32], q: f32) -> f32 {
    if sorted.is_empty() {
        return 0.0;
    }
    if sorted.len() == 1 {
        return sorted[0];
    }
    let q = q.clamp(0.0, 1.0);
    let pos = q * (sorted.len() as f32 - 1.0);
    let lo = pos.floor() as usize;
    let hi = pos.ceil() as usize;
    if lo == hi {
        sorted[lo]
    } else {
        let frac = pos - lo as f32;
        sorted[lo] * (1.0 - frac) + sorted[hi] * frac
    }
}
