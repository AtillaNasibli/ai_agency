"""LLM Council (Karpathy's idea): several models answer, rank each other anonymously, a chairman writes the final.

Stage 1  every member answers the question on its own
Stage 2  every member ranks the anonymised answers (A, B, C ...) - it never knows who wrote what
Stage 3  the chairman reads answers + rankings and writes the final answer

Members come from COUNCIL_MODELS ("ollama:llama3.1,ollama:llama3.2,openrouter:...") or, by default,
up to 3 different models installed in Ollama. Fewer than 2 distinct members -> no council.
"""
import os, random, re
import llm


def members():
    env = os.environ.get("COUNCIL_MODELS", "").strip()
    if env:
        out = [m.strip() for m in env.split(",") if m.strip()]
    else:
        out = []
        try:
            import requests
            tags = requests.get(f"{llm.ollama_host()}/api/tags", timeout=5).json().get("models", [])
            out = [f"ollama:{m['name']}" for m in tags][:3]
        except Exception:  # noqa: BLE001
            pass
    seen, uniq = set(), []
    for m in out:
        if m not in seen:
            seen.add(m); uniq.append(m)
    return uniq if len(uniq) >= 2 else []


def parse_ranking(text, labels):
    """Return labels in ranked order (best first) from a 'FINAL RANKING:' block; tolerant of messy output."""
    tail = text.split("FINAL RANKING:")[-1]
    found = []
    for lab in re.findall(r"Response ([A-Z])", tail):
        if lab in labels and lab not in found:
            found.append(lab)
    return found


def deliberate(system, question, member_specs=None, chairman=None):
    member_specs = member_specs or members()
    if len(member_specs) < 2:
        raise RuntimeError("council needs at least 2 different models")
    chairman = chairman or os.environ.get("COUNCIL_CHAIRMAN") or member_specs[0]
    metrics = dict(latency_s=0.0, prompt_tokens=0, completion_tokens=0, calls=0)

    def call(spec, sys_, usr):
        r = llm.complete(sys_, usr, spec)
        metrics["latency_s"] += r["latency_s"]; metrics["prompt_tokens"] += r["prompt_tokens"]
        metrics["completion_tokens"] += r["completion_tokens"]; metrics["calls"] += 1
        return r["text"]

    # Stage 1
    answers = {}
    for spec in member_specs:
        try:
            answers[spec] = call(spec, system, question)
        except Exception:  # noqa: BLE001
            pass
    if len(answers) < 2:
        raise RuntimeError("council: fewer than 2 members answered")
    # anonymise
    specs = list(answers); random.shuffle(specs)
    labels = {s: chr(65 + i) for i, s in enumerate(specs)}
    block = "\n\n".join(f"Response {labels[s]}:\n{answers[s]}" for s in sorted(specs, key=lambda x: labels[x]))
    # Stage 2
    rank_prompt = (f"Question:\n{question}\n\nHere are anonymous responses:\n\n{block}\n\n"
                   "Briefly evaluate each response, then finish with a line 'FINAL RANKING:' followed by a numbered "
                   "list, best first, using exactly the form '1. Response X'.")
    points = {l: [] for l in labels.values()}
    rankings = {}
    for spec in answers:
        try:
            order = parse_ranking(call(spec, system, rank_prompt), set(points))
        except Exception:  # noqa: BLE001
            continue
        rankings[spec] = order
        for pos, lab in enumerate(order, 1):
            points[lab].append(pos)
    avg = {lab: (sum(p) / len(p) if p else 99) for lab, p in points.items()}
    ordered = sorted(avg, key=avg.get)
    # Stage 3
    ranking_text = ", ".join(f"Response {l} (avg rank {avg[l]:.1f})" for l in ordered)
    final_prompt = (f"Question:\n{question}\n\nCouncil answers:\n\n{block}\n\nPeer ranking (best first): {ranking_text}\n\n"
                    "You are the chairman. Write the single best final answer, using the strongest points of the "
                    "responses. Be concrete and concise.")
    final = call(chairman, system, final_prompt)
    inv = {v: k for k, v in labels.items()}
    md = ["## Council final answer", f"_Chairman: {chairman}_", "", final, "",
          "## How the council voted", "Peer ranking (anonymous, best first):"]
    md += [f"{i}. Response {l} = {inv[l]} (avg rank {avg[l]:.1f})" for i, l in enumerate(ordered, 1)]
    md += ["", "## Individual answers"]
    md += [f"### {s}\n{answers[s]}\n" for s in specs]
    metrics["latency_s"] = round(metrics["latency_s"], 2)
    return dict(text="\n".join(md), members=list(answers), chairman=chairman, ranking=ordered, metrics=metrics)
