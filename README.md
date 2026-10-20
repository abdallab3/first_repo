# Bus Tracker

**Open the app: https://firstrepo-production-39dc.up.railway.app**

A web app that shows where buses are right now. Buses come from a transit agency's public live
feed. Riders can also choose to share their phone's location, which shows where their bus is on
routes the agency does not cover.

With no agency connected the app runs in **demo mode** with simulated buses, clearly labeled on
the page, so there is always something to see.

## How it works

1. **The agency's feed.** Most transit agencies publish live bus positions in a standard format
   called GTFS-Realtime (the vehicle positions feed). The app reads that feed, at most once every
   10 seconds however many people are watching, and shows each bus on the map with its route.
   Positions older than 5 minutes are hidden.
2. **Riders sharing.** A rider taps **Share my bus**, picks their route and agrees to share. Their
   phone sends its location every 5 seconds while the page is open. Riders on the same route who
   are close together are combined into one bus.
3. **Merging.** A rider on a bus the agency already reports does not add a second dot. They
   count as a confirmation on that bus.

## Privacy and safety

- Sharing is opt-in, and it stops when the rider taps Stop, closes the page, or goes quiet for
  two minutes.
- Other people see a bus, never a rider. Nothing that identifies a person is sent to the map.
- A rider who is standing still is not shown, so nobody appears on the map from home or from a
  bus stop. The dot appears once the bus has moved about 50 meters.
- Everything about riders is kept in memory only and forgotten within minutes. No accounts, no
  history, nothing written to disk.
- Positions are checked: bad coordinates, positions vaguer than 100 meters, and jumps faster
  than a bus can travel are refused. Each visitor is rate limited.

## Connect a transit agency

Set these in Railway (service, Variables). Only `FEED_URL` is required.

| Variable | What it does | Example |
| --- | --- | --- |
| `FEED_URL` | The agency's GTFS-Realtime vehicle positions address | `https://example.org/gtfs-rt/vehicle-positions` |
| `FEED_HEADERS` | Extra headers some agencies need, such as an API key, as JSON | `{"x-api-key": "YOUR_KEY"}` |
| `AGENCY_NAME` | Shown in the page header | `Metro Transit` |
| `MAP_CENTER` | Where the map opens, `latitude,longitude` | `41.88,-87.63` |
| `MAP_ZOOM` | How close the map opens (2 to 18) | `12` |
| `FEED_REFRESH_SECONDS` | Longest the app waits between feed requests (5 or more) | `10` |
| `TILE_URL`, `TILE_ATTRIBUTION` | The map picture provider (defaults to OpenStreetMap) | |

Some agencies put the key in the address (`...?key=YOUR_KEY`) and some in a header. Put it in
whichever place the agency's instructions say. Find your agency's feed on its developer page, or
in the Mobility Database or Transitland directories.

The default map pictures come from OpenStreetMap's free tile server, which is meant for light
use. Before many people use the app, switch `TILE_URL` to a tile provider you have an account with.

## Run it on your computer

```
pip install -r requirements-dev.txt
python -m app.main            # then open http://127.0.0.1:8000
python -m unittest discover -s tests -t .
```

Tests build their own sample feeds, so they never touch a real agency.

## Deploy on Railway

1. In Railway choose **New Project, Deploy from GitHub repo**, and pick this repository.
2. Railway reads `requirements.txt` and `railway.json`. `/health` is the health check.
3. In the service's **Settings, Networking**, click **Generate Domain**.

Every push to the main branch redeploys the site. Keep the app at **one worker**: rider
locations and rate limits are kept in memory, so more workers would each have their own copy.

## What it cannot do yet

- **Sharing with the screen off.** A web page can only read location while it is open on the
  screen. The page asks the phone to keep the screen on, but background sharing needs a phone
  app downloaded from an app store, which is a separate project. The server would stay the same.
- **Route names.** The feed gives route codes, which are sometimes not the number riders know. Reading the agency's
  schedule files (GTFS) would add names, stops and route lines.
- **Checking a rider is on the right bus.** Today the app checks that a rider is moving at bus
  speed, not that they are on the route's path.
- **Predicted arrival times.** Only current positions are shown.

The earlier Website Navigator is still in the repository history (commit `393a1db`).
