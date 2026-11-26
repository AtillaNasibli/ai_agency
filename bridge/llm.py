"""One door for every model call: LiteLLM (if installed) -> Ollama (local) or OpenRouter (cloud).

* LiteLLM  (litellm.ai)      unified OpenAI-style interface over 100+ providers. Used automatically
                             when the package is installed; otherwise a built-in HTTP path is used.
* OpenRouter (openrouter.ai) one API key, hundreds of cloud models. Used as the CLOUD fallback.
* Local-first policy (OpenJarvis idea): try the local Ollama model first, go to the cloud only
                             when local fails and OPENROUTER_API_KEY is set. Route: LLM_ROUTE=ollama,openrouter

Model spec strings: "ollama:llama3.2", "openrouter:google/gemini-2.0-flash-001", or a bare name (= ollama).
Every call returns metrics (latency, tokens, provider) so efficiency can be reported.
"""
import os, time

try:
    import litellm  # optional
    litellm.suppress_debug_info = True
except Exception:  # noqa: BLE001
    litellm = None


def ollama_host():
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")


def default_model(provider):
    if provider == "ollama":
        return os.environ.get("OLLAMA_MODEL", "llama3.1")
    return os.environ.get("OPENROUTER_MODEL", "openrouter/auto")


def parse_spec(spec):
    if ":" in spec and spec.split(":", 1)[0] in ("ollama", "openrouter"):
        p, m = spec.split(":", 1)
        return p, m
    return "ollama", spec


def _call_ollama(model, messages):
    t0 = time.time()
    if litellm is not None:
        r = litellm.completion(model=f"ollama_chat/{model}", messages=messages, api_base=ollama_host(), timeout=600)
        u = getattr(r, "usage", None)
        return dict(text=r.choices[0].message.content.strip(), via="litellm",
                    ptok=getattr(u, "prompt_tokens", 0) or 0, ctok=getattr(u, "completion_tokens", 0) or 0,
                    latency=time.time() - t0)
    import requests
    r = requests.post(f"{ollama_host()}/api/chat", timeout=600,
                      json={"model": model, "stream": False, "messages": messages})
    r.raise_for_status()
    j = r.json()
    return dict(text=j["message"]["content"].strip(), via="http",
                ptok=j.get("prompt_eval_count", 0), ctok=j.get("eval_count", 0), latency=time.time() - t0)


def _call_openrouter(model, messages):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    t0 = time.time()
    if litellm is not None:
        name = model if model.startswith("openrouter/") else f"openrouter/{model}"
        r = litellm.completion(model=name, messages=messages, api_key=key, timeout=300)
        u = getattr(r, "usage", None)
        return dict(text=r.choices[0].message.content.strip(), via="litellm",
                    ptok=getattr(u, "prompt_tokens", 0) or 0, ctok=getattr(u, "completion_tokens", 0) or 0,
                    latency=time.time() - t0)
    import requests
    base = os.environ.get("OPENROUTER_BASE", "https://openrouter.ai/api/v1").rstrip("/")
    name = model[len("openrouter/"):] if model.startswith("openrouter/") and model != "openrouter/auto" else model
    r = requests.post(f"{base}/chat/completions", timeout=300,
                      headers={"Authorization": f"Bearer {key}"},
                      json={"model": name, "messages": messages})
    r.raise_for_status()
    j = r.json()
    u = j.get("usage", {})
    return dict(text=j["choices"][0]["message"]["content"].strip(), via="http",
                ptok=u.get("prompt_tokens", 0), ctok=u.get("completion_tokens", 0), latency=time.time() - t0)


CALLERS = {"ollama": _call_ollama, "openrouter": _call_openrouter}


def complete(system, user, spec=None):
    """Return dict(text, provider, model, via, latency_s, prompt_tokens, completion_tokens, fallback).
    With spec=None the LLM_ROUTE order is followed (local first). With an explicit spec there is no fallback."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if spec:
        route = [parse_spec(spec)]
    else:
        route = [(p.strip(), default_model(p.strip())) for p in os.environ.get("LLM_ROUTE", "ollama,openrouter").split(",") if p.strip() in CALLERS]
    errors = []
    for i, (prov, model) in enumerate(route):
        try:
            r = CALLERS[prov](model, messages)
            return dict(text=r["text"], provider=prov, model=model, via=r["via"], latency_s=round(r["latency"], 2),
                        prompt_tokens=r["ptok"], completion_tokens=r["ctok"], fallback=i > 0)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{prov}: {type(e).__name__}")
    raise RuntimeError("all model routes failed -> " + "; ".join(errors))
