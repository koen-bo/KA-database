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
