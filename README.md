# Sports Plus daily trivia kit

This branch holds the renderer that turns a day's trivia question into post files:

- `render_slides.py` makes the TikTok slides (1080×1920), the Instagram/Facebook slides (1080×1350) and the animated YouTube Short.
- `fonts/` holds TeX Gyre Heros, the free Helvetica-style stand-in for the brand's Helvetica Neue.
- `brand/` holds the Sports Plus logos from the brand book.
- `.github/workflows/render.yml` runs the renderer on GitHub whenever a new `jobs/<date>/trivia.json` is pushed here, then rewrites the `posts` branch as a single commit with that day's files plus the last 7 days of folders.

The daily Claude task writes `jobs/<date>/trivia.json`, waits for the `posts` branch to update, then schedules the posts in Metricool.

## trivia.json

```json
{
  "sport": "Baseball",
  "date": "2026-10-08",
  "question": "…",
  "choices": ["2 games", "47 games", "312 games", "They're under .500"],
  "answer": "A: Just 2 games",
  "answer_detail": "…",
  "source": "Baseball-Reference"
}
```

On tote Fridays it also has `promo_tag` and `promo`.
