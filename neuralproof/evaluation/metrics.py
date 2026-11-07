import math,statistics

def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased pass@k estimator (Chen et al. 2021)."""
    if n <= 0 or k <= 0 or n < k:
        return 0.0
    if n - c < k:
        return 1.0
    return 1.0 - math.prod((n - c - i) / (n - i) for i in range(k))

def summarize(results):
    n=len(results); solved=sum(bool(x.get("verified")) for x in results); rate=solved/n if n else 0.0
    z=1.96; den=1+z*z/n if n else 1; center=(rate+z*z/(2*n))/den if n else 0
    half=z*math.sqrt(rate*(1-rate)/n+z*z/(4*n*n))/den if n else 0
    times=[float(x["solve_seconds"]) for x in results if x.get("verified") and "solve_seconds" in x]
    token_counts=[x["inference_tokens"] for x in results if x.get("inference_tokens") is not None]
    
    # Calculate pass@10 only when repeated samples per theorem exist (attempts >= 10)
    has_repeat_samples = n > 0 and all(x.get("attempts", 1) >= 10 for x in results)
    if has_repeat_samples:
        p10 = sum(pass_at_k(x["attempts"], x.get("verified_attempts", int(x.get("verified", False))), 10) for x in results) / n
        p10_note = "unbiased pass@10 across repeat samples"
    else:
        p10 = None
        p10_note = "not measured: benchmark currently records one search run per theorem"

    return {"attempted":n,"verified":solved,"solve_rate":rate,"solve_rate_wilson95":[max(0,center-half),min(1,center+half)] if n else None,
            "pass_at_1":rate,"pass_at_10":p10,"pass_at_10_note":p10_note,
            "pass_at_1_protocol":"one bounded search run per theorem; no repeat samples" if not has_repeat_samples else "mean pass@1 across repeat samples",
            "mean_solve_seconds":sum(times)/len(times) if times else None,"median_solve_seconds":statistics.median(times) if times else None,
            "mean_nodes_expanded":sum(x.get("expanded",0) for x in results)/n if n else None,
            "mean_tactic_calls":sum(x.get("tactic_calls",0) for x in results)/n if n else None,
            "invalid_tactics":sum(x.get("invalid_tactics",0) for x in results),
            "timeouts":sum(x.get("timeouts",0) for x in results),
            "rejected_unknown_lemmas":sum(x.get("rejected_unknown_lemmas",0) for x in results),
            "inference_tokens":sum(token_counts) if token_counts else None,
            "gpu_seconds":None,"gpu_memory_mb":None}
