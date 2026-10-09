# Website Navigator

A web app where you enter a website address and tell it what to find, such as
"find the 2026 school calendar page". It looks through the site and links you to the best match.

It does not use any AI service. It reads a site's sitemap and pages, scores each page against your
request, and shows the best page first with the reason it matched.

## How a search works

1. **Check the address.** Only public `http` and `https` websites on the normal ports are allowed.
   Addresses that point to private or internal networks are refused, and so is every redirect that
   would lead there.
2. **Read the site's rules.** `robots.txt` is read first and obeyed, including `*` and `$` wildcards
   and `Crawl-delay`. If it cannot be read, the site is not searched.
3. **Find pages.** The sitemap (if the site has one) gives a head start. Then the crawler follows
   links on the same site, most promising links first, one request at a time with a pause between
   requests. Links to PDFs and other documents are scored by their link text and file name and are
   never downloaded.
4. **Understand the request.** Filler words ("find", "the", "page", "subpage") are dropped. Years
   are pulled out, and `2026-27` counts as both 2026 and 2027. Related words match too, so
   "calendar" also finds "schedule" and "dates".
5. **Score pages.** Link text and titles count most, then the address, headings and the page text.
   A page that covers every word beats one that covers a single word very well. A page for the
   right year is boosted, and a page labelled with a different year is pushed down.
6. **Answer.** The best match comes first, followed by up to three other options, each with the
   reasons it matched. Nothing is stored.

## Limits that keep it polite and safe

| Limit | Default | Setting |
| --- | --- | --- |
| Pages read per search | 40 | `MAX_PAGES` |
| Seconds per search | 25 | `MAX_SECONDS` |
| Pause between requests | 0.4 s (or the site's Crawl-delay, up to 5 s) | `REQUEST_DELAY` |
| Searches per visitor | 10 per 10 minutes | `RATE_LIMIT_SEARCHES`, `RATE_LIMIT_WINDOW` |
| Searches running at once | 4 | `MAX_CONCURRENT` |
| Proxies in front of the app | 1 (Railway) | `TRUSTED_PROXY_HOPS` |

Each page is cut off after 1 MB, and each search remembers at most 3,000 links.

## Run it on your computer

```
pip install -r requirements-dev.txt
python -m app.main            # then open http://127.0.0.1:8000
python -m pytest              # or: python -m unittest discover -s tests -t .
```

Searching your own computer or local network is refused on purpose, so local test sites will not
work. The tests use a saved sample school website instead (`tests/fakesite.py`).

## Deploy on Railway

1. In Railway choose **New Project, Deploy from GitHub repo**, and pick this repository.
2. Railway reads `requirements.txt` and `railway.json`. The start command is
   `gunicorn app.main:app --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 120`, and
   `/health` is the health check.
3. In the service's **Settings, Networking**, click **Generate Domain**.

Every push to the main branch redeploys the site. Keep the app at **one worker**: the rate limit and
the server-wide search cap are kept in memory, so more workers would each count separately.

## What it cannot do yet

- Pages that only show their content after JavaScript runs. The app warns when a site looks like this.
- Pages behind a sign-in.
- It checks every address before connecting, but it does not pin the connection to the checked IP
  address, so a hostile DNS server that changes its answer between the check and the connection
  could in theory get through. Keep secrets and internal services off any network the app can reach.
