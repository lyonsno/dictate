"""Benchmark: sync barrier vs async-only decode loop in mlx_whisper.

Compares the patched _main_loop (mx.eval on completed flag per iteration)
against the original (mx.async_eval for everything) on real audio.

Usage:
    uv run python bench_decode_sync.py [--runs N] [--duration SEC] [--model REPO]
    uv run python bench_decode_sync.py --sweep          # all models × durations

Outputs per-segment decode times for both variants, plus summary stats.
"""

import argparse
import json
import os
import platform
import socket
import subprocess
import time

import mlx.core as mx
import numpy as np

import mlx_whisper
from mlx_whisper.decoding import DecodingTask


def _main_loop_sync(self, audio_features, tokens):
    """Patched: mx.eval(next_completed) per iteration."""
    n_batch = tokens.shape[0]
    sum_logprobs = mx.zeros(n_batch)

    def _step(inputs, audio_features, tokens, sum_logprobs):
        pre_logits = self.inference.logits(inputs, audio_features)
        logits = pre_logits[:, -1]
        for logit_filter in self.logit_filters:
            logits = logit_filter.apply(logits, tokens)
        tokens, completed, sum_logprobs = self.decoder.update(
            tokens, logits, sum_logprobs
        )
        return tokens, completed, sum_logprobs, pre_logits

    tokens, completed, sum_logprobs, pre_logits = _step(
        tokens, audio_features, tokens, sum_logprobs
    )
    if self.tokenizer.no_speech is not None:
        probs_at_sot = mx.softmax(pre_logits[:, self.sot_index], axis=-1)
        no_speech_probs = probs_at_sot[:, self.tokenizer.no_speech]
    else:
        no_speech_probs = mx.full(n_batch, mx.nan)
    mx.async_eval(completed, tokens, sum_logprobs, no_speech_probs)

    for i in range(1, self.sample_len):
        inputs = tokens[:, -1:]
        if tokens.shape[-1] > self.n_ctx:
            break
        next_tokens, next_completed, next_sum_logprobs, _ = _step(
            inputs, audio_features, tokens, sum_logprobs
        )
        mx.eval(next_completed)
        if completed:
            break
        tokens = next_tokens
        completed = next_completed
        sum_logprobs = next_sum_logprobs
        mx.async_eval(next_tokens, next_sum_logprobs)

    return tokens, sum_logprobs, no_speech_probs


def _main_loop_async(self, audio_features, tokens):
    """Original: mx.async_eval for everything, no sync barrier."""
    n_batch = tokens.shape[0]
    sum_logprobs = mx.zeros(n_batch)

    def _step(inputs, audio_features, tokens, sum_logprobs):
        pre_logits = self.inference.logits(inputs, audio_features)
        logits = pre_logits[:, -1]
        for logit_filter in self.logit_filters:
            logits = logit_filter.apply(logits, tokens)
        tokens, completed, sum_logprobs = self.decoder.update(
            tokens, logits, sum_logprobs
        )
        return tokens, completed, sum_logprobs, pre_logits

    tokens, completed, sum_logprobs, pre_logits = _step(
        tokens, audio_features, tokens, sum_logprobs
    )
    if self.tokenizer.no_speech is not None:
        probs_at_sot = mx.softmax(pre_logits[:, self.sot_index], axis=-1)
        no_speech_probs = probs_at_sot[:, self.tokenizer.no_speech]
    else:
        no_speech_probs = mx.full(n_batch, mx.nan)
    mx.async_eval(completed, tokens, sum_logprobs, no_speech_probs)

    for i in range(1, self.sample_len):
        inputs = tokens[:, -1:]
        if tokens.shape[-1] > self.n_ctx:
            break
        next_tokens, next_completed, next_sum_logprobs, _ = _step(
            inputs, audio_features, tokens, sum_logprobs
        )
        mx.async_eval(next_completed, next_tokens, next_sum_logprobs)
        if completed:
            break
        tokens = next_tokens
        completed = next_completed
        sum_logprobs = next_sum_logprobs

    return tokens, sum_logprobs, no_speech_probs


def get_machine_info():
    """Collect machine identifiers for the report."""
    hostname = socket.gethostname()
    try:
        chip = subprocess.check_output(
            ["sysctl", "-n", "machdep.cpu.brand_string"], text=True
        ).strip()
    except Exception:
        chip = "unknown"
    ram_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    ram_gb = ram_bytes / (1024 ** 3)
    return {
        "hostname": hostname,
        "chip": chip,
        "ram_gb": round(ram_gb),
        "platform": platform.platform(),
    }


def generate_test_audio(duration_sec=10.0, sr=16000):
    n_samples = int(duration_sec * sr)
    return np.random.randn(n_samples).astype(np.float32) * 0.1


def load_and_trim_audio(path, duration_sec, sr=16000):
    """Load audio file via ffmpeg and trim to duration_sec."""
    import subprocess
    cmd = [
        "ffmpeg", "-nostdin", "-i", path,
        "-t", str(duration_sec),
        "-threads", "0", "-f", "s16le", "-ac", "1",
        "-acodec", "pcm_s16le", "-ar", str(sr), "-",
    ]
    out = subprocess.run(cmd, capture_output=True, check=True).stdout
    pcm = np.frombuffer(out, np.int16)
    return pcm.astype(np.float32) / 32768.0


def benchmark_variant(name, main_loop_fn, model_repo, audio, n_runs=5):
    """Run one variant n_runs times, return list of times in ms."""
    original = DecodingTask._main_loop
    DecodingTask._main_loop = main_loop_fn

    times = []
    for run in range(n_runs):
        mx.eval(mx.zeros(1))

        t0 = time.monotonic()
        result = mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=model_repo,
            language="en",
            verbose=False,
        )
        t1 = time.monotonic()
        total_ms = (t1 - t0) * 1000
        text = result.get("text", "").strip()
        times.append(total_ms)
        print(f"  {name} run {run + 1}: {total_ms:7.1f}ms  ({len(text)} chars)")

    DecodingTask._main_loop = original
    return times


def run_single(model_repo, duration, n_runs, audio_path=None):
    """Benchmark one model at one duration. Returns result dict."""
    print(f"\n{'─' * 60}")
    print(f"Model: {model_repo}")
    print(f"Duration: {duration}s | Runs: {n_runs}")
    print(f"{'─' * 60}")

    # Warm up model
    dummy = np.zeros(16000, dtype=np.float32)
    mlx_whisper.transcribe(dummy, path_or_hf_repo=model_repo, language="en")

    if audio_path:
        audio = load_and_trim_audio(audio_path, duration)
    else:
        audio = generate_test_audio(duration)

    print("\nSYNC (patched):")
    sync_times = benchmark_variant("sync", _main_loop_sync, model_repo, audio, n_runs)

    print("\nASYNC (original):")
    async_times = benchmark_variant("async", _main_loop_async, model_repo, audio, n_runs)

    # Steady-state: drop first run if possible
    if n_runs > 2:
        sync_steady = sync_times[1:]
        async_steady = async_times[1:]
    else:
        sync_steady = sync_times
        async_steady = async_times

    sync_mean = np.mean(sync_steady)
    async_mean = np.mean(async_steady)
    diff_ms = sync_mean - async_mean
    diff_pct = (diff_ms / async_mean) * 100 if async_mean > 0 else 0
    direction = "slower" if diff_ms > 0 else "faster"

    print(f"\n  SYNC:  {sync_mean:7.1f}ms ± {np.std(sync_steady):5.1f}ms")
    print(f"  ASYNC: {async_mean:7.1f}ms ± {np.std(async_steady):5.1f}ms")
    print(f"  Sync is {abs(diff_ms):.1f}ms ({abs(diff_pct):.1f}%) {direction}")

    return {
        "model": model_repo,
        "duration_sec": duration,
        "n_runs": n_runs,
        "sync_times_ms": sync_times,
        "async_times_ms": async_times,
        "sync_steady_mean_ms": round(sync_mean, 1),
        "async_steady_mean_ms": round(async_mean, 1),
        "diff_ms": round(diff_ms, 1),
        "diff_pct": round(diff_pct, 1),
        "direction": direction,
    }


SWEEP_MODELS = [
    "mlx-community/whisper-medium.en-mlx-4bit",
    "mlx-community/whisper-medium.en-mlx-8bit",
    "mlx-community/whisper-medium.en-mlx",
    "mlx-community/whisper-large-v3-turbo-4bit",
    "mlx-community/whisper-large-v3-turbo-8bit",
    "mlx-community/whisper-large-v3-turbo",
]

SWEEP_DURATIONS = [5, 10, 15, 30, 60, 120, 180]


def main():
    parser = argparse.ArgumentParser(description="Benchmark decode sync barrier")
    parser.add_argument("--runs", type=int, default=5, help="Runs per variant")
    parser.add_argument("--model", type=str, default=None, help="HF model repo")
    parser.add_argument("--duration", type=float, default=15.0, help="Audio duration (seconds)")
    parser.add_argument("--sweep", action="store_true", help="Run all models × durations")
    parser.add_argument("--audio", type=str, default=None, help="Audio file for realistic input")
    parser.add_argument("--output", type=str, default=None, help="Save JSON results to file")
    args = parser.parse_args()

    machine = get_machine_info()
    print(f"Machine: {machine['hostname']} — {machine['chip']} — {machine['ram_gb']}GB")

    results = []

    if args.audio:
        print(f"Audio source: {args.audio}")

    if args.sweep:
        for model in SWEEP_MODELS:
            for dur in SWEEP_DURATIONS:
                try:
                    r = run_single(model, dur, args.runs, audio_path=args.audio)
                    results.append(r)
                except Exception as e:
                    print(f"\n  FAILED: {model} @ {dur}s — {e}")
                    results.append({
                        "model": model, "duration_sec": dur,
                        "error": str(e),
                    })
    else:
        model = args.model or "mlx-community/whisper-large-v3-turbo"
        r = run_single(model, args.duration, args.runs, audio_path=args.audio)
        results.append(r)

    # Summary table
    print(f"\n{'=' * 70}")
    print(f"SUMMARY — {machine['hostname']} ({machine['chip']}, {machine['ram_gb']}GB)")
    print(f"{'=' * 70}")
    print(f"{'Model':>45s} {'Dur':>4s} {'Sync':>8s} {'Async':>8s} {'Diff':>10s}")
    print(f"{'─' * 45} {'─' * 4} {'─' * 8} {'─' * 8} {'─' * 10}")
    for r in results:
        if "error" in r:
            print(f"{r['model']:>45s} {r['duration_sec']:>3.0f}s {'FAILED':>8s}")
            continue
        sign = "+" if r["diff_ms"] > 0 else ""
        print(
            f"{r['model']:>45s} {r['duration_sec']:>3.0f}s "
            f"{r['sync_steady_mean_ms']:>7.0f}ms {r['async_steady_mean_ms']:>7.0f}ms "
            f"{sign}{r['diff_ms']:>6.0f}ms ({sign}{r['diff_pct']:.1f}%)"
        )

    # Save JSON
    output_path = args.output or f"bench_results_{machine['hostname']}.json"
    report = {"machine": machine, "results": results}
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
