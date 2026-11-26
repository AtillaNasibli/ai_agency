# AI Marketing & Growth Agency - 8 autonomous AI employees

Built on [markfulton/ai-employees](https://github.com/markfulton/ai-employees) (MIT).
Agency type: **AI Marketing Agency (SEO/AEO)**. 8 employees, the **Chief of Staff** is the Project Manager.

## Run it (one command, then hands off)
1. Install [Ollama](https://ollama.com) and pull a model: `ollama pull llama3.1`
2. Windows: double-click **`start.bat`** (Linux/macOS: `./start.sh`)

The app then works **by itself, in a loop** (default every 60 min, `CYCLE_MINUTES` in `.env`):

```
 7 employees draft their task (local Ollama)  ->  Chief of Staff (PM) summarises
        |                                                  |
   employees/<role>/outputs/*.md + runlog.jsonl            |
                         |                                 |
                 PM audit (bridge/collect.py)              |
                   |                         |             |
      Google Sheet ledger rows       Daily e-mail brief (once per day)
 [Timestamp | Agent Name | Task Performed | Output Status]
```
Live dashboard: **http://127.0.0.1:8080** (opens automatically): per-employee status, latest drafts, activity log.

## Optional: Google Sheet + e-mail (fill `.env`, then it happens automatically)
- Sheet: Google Cloud service account + Sheets API, save key as `service_account.json`, share the sheet with the service-account e-mail (Editor), set `SHEET_ID`.
- E-mail: Gmail **app password** in `SMTP_APP_PASSWORD`, set `SMTP_USER` and `MAIL_TO`.
Without them the agency still runs; the dashboard shows "not configured".

## Course links implemented (what each one does in this project)
| Link | Where in the code | What it does here |
|---|---|---|
| [LiteLLM](https://www.litellm.ai/) | `bridge/llm.py` | One OpenAI-style call for every model. Used automatically when `litellm` is installed (`requirements-litellm.txt`); otherwise a built-in HTTP path does the same job. |
| [OpenRouter](https://openrouter.ai/pricing) | `bridge/llm.py` (`OPENROUTER_API_KEY`) | Cloud fallback and cloud council members: one key, many models. Pay-as-you-go; see their pricing page. |
| [LLM Council](https://github.com/karpathy/llm-council) | `bridge/council.py` | The Chief of Staff's weekly decision brief is written by a council: models answer, rank each other anonymously, a chairman writes the final answer. Needs 2+ different models. |
| [OpenJarvis](https://openjarvis.stanford.edu/) | `bridge/llm.py`, dashboard | Its local-first idea: Ollama first, cloud only if local fails (`LLM_ROUTE`), plus efficiency metrics (latency, tokens, local share) per run in `metrics.jsonl` and on the dashboard. The OpenJarvis package itself is not bundled. |

Council setup: `ollama pull llama3.2` (a 2nd model) or set `COUNCIL_MODELS` in `.env`.

## Files
| Path | Purpose |
|---|---|
| `app.py` | Autonomous scheduler + dashboard |
| `bridge/ollama_agent.py` | Runs one employee task (local first), writes draft + run log + metrics |
| `bridge/llm.py`, `bridge/council.py` | LiteLLM/Ollama/OpenRouter routing; Karpathy-style LLM council |
| `bridge/collect.py` | PM audit: reads each `runlog.jsonl` -> status |
| `bridge/sheet_logger.py`, `bridge/daily_brief.py` | Google Sheet ledger, HTML/text e-mail |
| `bridge/run_daily.py` | One-shot PM report (`--demo`, `--dry-run`) |
| `config/agency.json`, `config/ollama_tasks.json` | Roles and each employee's task |
| `employees/*` | The 8 official kits with `.installed.json` receipts (full Claude Code/harness versions) |
| `tests/` | Offline tests: `python -m unittest discover -s tests -v` |

## Safety
Employees only produce **drafts**; nothing is sent, posted or spent. Credentials stay in `.env` / `service_account.json` (git-ignored) and are used only by the bridge, never by employees. The local runner is a lightweight mode; the full kits in `employees/` can also be run by a harness such as Claude Code.
