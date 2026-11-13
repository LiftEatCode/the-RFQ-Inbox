# AI usage

## Setup

- **Tool:** Claude Code (desktop app). TODO: confirm tool and model for the sessions before
  10:38 on 13 Nov (skeleton, scorer, reader, first CLAUDE.md).
- **Instruction file:** `CLAUDE.md` (in the repo): the task in one paragraph, hard rules
  (key never in the repo or logs, don't fit dev, flag when unsure), how we work (TDD, the
  human commits), layout, status, and what the dev data taught us.
- No subagents, skills or MCP servers were used for the work. `parse` uses the provided OpenAI
  key; the coding agent ran on my own account.

## How I worked

One chunk per pair of commits: the agent wrote failing tests and stopped; I read them and
committed "... (failing)"; then it wrote the code and I committed that. I ran every paid
`parse` myself and pasted the output back; the agent never handled the key. After each
behaviour change it replayed dev from the cache, scored it, and added a row to
`eval/history.md`. I reviewed by reading the tests (they state the behaviour), the score
diff, and the agent's list of judgment calls, and I pushed back on those: three of them were
revisited and one was changed. When the score looked too good I had it build a probe set of
invented emails to test on something that was not dev.

## Three moments

Session for all three: `ai-sessions/94cd2907-9e0a-412a-a5d5-a77d0da96bdb.jsonl`.

**The agent was wrong, and how I caught it.** Prompt v1 (`d63ae0f`) used three phrases
copied from dev emails as examples. The agent's own leak test passed because it only compared
the prompt with answer-key lines, senders and subjects. Before prompt v2 I reminded it of the
"don't fit dev" rule; it wrote stricter guards (`41c136e`: no five-word run, name or part
number from any dev email), which failed on v1, and v2 (`874c5ed`) removed the phrases.

**I overruled it.** The agent kept the rule "read the key from the environment only" and
gave me shell commands to load `.env`; they did not work from the app's command box and cost
several failed runs. I told it to load `.env` in code. It did (`e1bb609`), and added what I
had not asked for but needed: the real environment wins, and tests switch loading off so
`pytest` can never spend the key.

**It saved me real time.** One scanned form had 12 wrong quantities. Instead of rewording
the prompt, the agent rendered the page at the size the provider shrinks images to, showed
the digits were illegible there and clear at full size, and sent large pages as
full-resolution bands (`6c85c9d` tests, `b46e551` code). Quantity accuracy went from 94.3%
to 100% with one email re-read for 3.5 cents.
