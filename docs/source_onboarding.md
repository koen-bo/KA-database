# Source Onboarding Notes

This project now supports source methods:
- `rss`
- `sitemap`
- `listing`

## Priority Rule
Per organization, configure only one active method in `sources.txt`:
1. RSS
2. Sitemap
3. Listing

## File format
`sources.txt` lines:

`method | source_name | url | options_json`

Examples:
- `rss | IPLO - Water | https://iplo.nl/thema/water/nieuws-water/?rss=true | {}`
- `sitemap | Deltares - Nieuws | https://www.deltares.nl/sitemap.xml | {"include_prefixes":["https://www.deltares.nl/nieuws"]}`
- `listing | STOWA - Nieuws | https://www.stowa.nl/nieuws | {"selector_key":"stowa_nieuws","max_pages":2}`

## Listing selectors
Use `listing_selectors.json` and reference keys via `options_json.selector_key`.
Avoid adding hardcoded parser logic to `modules/discovery_listing.py`.

## Conservative defaults
- `KA_MAX_CANDIDATES_PER_SOURCE=60`
- `KA_MAX_SITEMAP_URLS_PER_SOURCE=120`
- `KA_MAX_LISTING_PAGES_PER_SOURCE=2`
- `KA_MAX_ENTRIES_PER_FEED=50` (existing RSS cap)
