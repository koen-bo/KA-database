# Feature Log

This file is a parking place for feature ideas that are promising, but not ready to implement yet.

## Tweede Kamer Search as a Supplemental Parliament Monitor

Status: Parked

Context:
- The current `Tweede Kamer` RSS feed is too weak for chamber-document discovery.
- The live RSS feed can miss relevant `Kamerstukken` that are visible through the Tweede Kamer search interface.
- Example gap observed on March 27, 2026:
  - `Voorjaarsbrief klimaat en energie`
  - `Geannoteerde Agenda ... Development Committee van de Wereldbank`
- Tweede Kamer search appears to use a richer internal index than the public RSS feed.

Why not now:
- This starts to behave like a separate product flow rather than a small source tweak.
- If we apply the current global keyword set directly to Tweede Kamer search results, the database could grow too quickly.
- Some Tweede Kamer items are thin landing pages with important content hidden in attachments, including `.docx`, which our current recovery path does not handle.

Promising direction:
- Treat Tweede Kamer search as a supplemental parliament-discovery layer, not as a replacement for RSS ingestion.
- Use a short curated query set instead of the full keyword universe.
- Keep the search results in a separate reviewable queue or dedicated monitoring view before promoting them into the main database.
- Apply stricter source-specific rules than the normal RSS filter.
- Prefer a small set of high-value document types first, such as `brieven regering` and related policy documents.

Potential v1 shape:
- Add a dedicated Tweede Kamer search collector with 5-8 fixed strategic queries.
- Store hits in a separate `parliament_candidates`-style queue/table or a dedicated dashboard page.
- Add hard dedupe against existing DB URLs.
- Only auto-promote stronger hits, or require manual review for promotion.
- Consider optional attachment expansion later, including `.docx`, if the review flow proves valuable.

Open questions for later:
- Which search queries should be fixed in v1?
- Should this live inside the current dashboard or as a separate app/workflow?
- Do we want manual triage, stricter auto-promotion, or both?
- Is `.docx` extraction worth adding for parliament-only sources?

## Coolify Worker Misconfiguration / Container Follow-up

Status: Parked

Context:
- The supposed ingestion worker in Coolify is currently not running a worker command.
- It is running the same dashboard startup command as the main app:
  - `streamlit run dashboard.py --server.address=0.0.0.0 --server.port=8501`
- The active pipeline run was observed inside the main dashboard container as a child process of Streamlit:
  - parent: `jgck0wc80ok00co0gss8oogg`
  - child process: `python main.py`

Relevant container names observed on March 27, 2026:
- Current dashboard container:
  - `jgck0wc80ok00co0gss8oogg`
- Supposed worker container, but actually also running Streamlit:
  - `pksgooo8o0848sss88g4oc8c-201425259920`
- Older dashboard container still present:
  - `jgck0wc80ok00co0gss8oogg-184125005480`

What this means:
- This is not a fatal architecture mistake.
- The app still works, and ingestion can still be triggered from the dashboard.
- The problem is operational clarity and container role separation, not a broken product model.
- It can lead to confusion, overlapping triggers, and lock-file warnings, but it is fixable without redesigning the application.

Likely cleanup path later:
- Keep one dashboard service for Streamlit.
- Replace the current “worker” service with scheduled jobs for:
  - `python main.py`
  - later optionally `python screen_documents.py ...`
- Clean up stale/older dashboard containers once the deployment shape is stabilized.

Open questions for later:
- Do we want `dashboard + scheduled tasks` only?
- Or do we truly need a long-running dedicated worker service?
- Which Coolify project should own ingestion cadence and screening cadence?
