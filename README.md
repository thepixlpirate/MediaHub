# MediaHub

<img src="static/icon.png" width="96" alt="MediaHub icon">

One web page, behind one login, for running your media apps:

**Radarr · Sonarr · Lidarr · Bookarr · qBittorrent · SABnzbd**

Each app gets its own tab (a dropdown on phones), with a dark interface that works on desktop and mobile. Each app has its own color and icon. Everything you'd normally open the apps for is built in, so you can stop visiting them one by one.

## What's included

**Overview** (click the MediaHub logo): totals for movies, shows, music and books, recently downloaded media, live downloads, upcoming releases, things that need attention, storage and app status.

**Alerts bell:** shows newly downloaded media and download-client connection problems. Routine indexer warnings are left out.


**Radarr, Sonarr, Lidarr**
- Library, calendar, wanted (missing and cutoff not met), and activity (queue, history, blocklist)
- Add, edit, delete, monitor, search and interactive search with sorting and filters
- **Manual import** for stuck downloads or any folder, with movie / series + episode / artist + album matching
- **Rename files** with a preview, plus bulk rename. Lidarr can also **retag** files
- **Per-item history**, with "mark as failed"
- **Full settings**: media management and naming (with a name preview), root folders, quality profiles, quality sizes, custom formats (paste JSON from TRaSH Guides), delay and release profiles, metadata profiles, indexers, download clients, remote path mappings, lists and exclusions, connections, metadata, tags, general settings, backups, logs, tasks and updates

**qBittorrent**: torrents, add, categories and tags, details (files, trackers, peers), options, **RSS feeds and auto-download rules**, **search and search plugins**, log

**SABnzbd**: queue, history, add NZB, warnings, stats, settings, categories, servers, **RSS feeds and filters**, **scheduler**

**Bookarr**: library, add, wanted, activity and settings

## How it works

- `server.py` is a small Python web server that uses only the standard library, so nothing needs installing.
- It has its own login (set on first run). API keys and passwords for your apps are stored on the server in `/config/hub.db` and are **never sent to the browser**.
- The browser talks only to MediaHub, and MediaHub talks to your apps. For each app it tries the **local URL** first, then the **remote URL**.

## Install

Every push to `main` builds a ready-to-run image with GitHub Actions (`.github/workflows/docker.yml`) and publishes it to `ghcr.io/<your-github-name>/<repo-name>`. Version tags like `v1.2.0` also get their own image tag. Images are built for both regular PCs/servers (amd64) and ARM boards (arm64).

> After the first build, open your GitHub profile → **Packages** → the MediaHub package → **Package settings** → **Change visibility** → **Public**, so your server can download it without signing in.

### Unraid

Use the template in `unraid/mediahub.xml`: replace `YOUR-GITHUB-NAME`, copy it to `/boot/config/plugins/dockerMan/templates-user/my-MediaHub.xml`, then choose it under **Docker → Add Container → Template**. Or fill in Add Container by hand:

- **Repository:** `ghcr.io/<your-github-name>/<repo-name>:latest`
- **Icon URL:** `https://raw.githubusercontent.com/<your-github-name>/<repo-name>/main/static/icon.png`
- **WebUI:** `http://[IP]:[PORT:8690]/`
- **Port:** 8690 → 8690
- **Path:** `/config` → an appdata folder. Reuse your old container's config folder to keep your login and settings.

To update, push your changes to GitHub, wait for the Action to finish (about 2 minutes), then use **Check for Updates** on the Docker tab.

### Docker

```bash
docker run -d --name mediahub \
  -p 8690:8690 \
  -v /path/to/mediahub-config:/config \
  --restart unless-stopped \
  ghcr.io/<your-github-name>/<repo-name>:latest
```

Or build it yourself: `docker build -t mediahub .`

Then open `http://<your-server>:8690`, create your login, open each tab, and go to **Settings → Connection** to enter that app's address and API key (or username and password for qBittorrent).

### Settings (environment variables)

| Variable | Default | What it does |
|---|---|---|
| `HUB_PORT` | `8690` | Port to listen on |
| `HUB_CONFIG` | `/config` | Where the database and image cache are kept |
| `HUB_TRUST_PROXY` | off | Set to `1` when running behind a reverse proxy or tunnel, so login rate limits see real visitor addresses |

### Access from outside your home

Put MediaHub behind HTTPS (for example a reverse proxy or Cloudflare Tunnel) and set `HUB_TRUST_PROXY=1`. Only MediaHub needs to be reachable. Your apps can stay private on your home network.

## Updating

Pull the new image (Unraid: **Check for Updates**). If a page ever says "Update needed", your browser has an old copy of the page cached; refresh it.

## Notes

- MediaHub can't change the apps' port, login, HTTPS or API key settings, so it can't cut off its own connection. Change those in the app itself.
- Restoring an app's backup, and the one-time sign-in some lists need (Trakt, Plex), are done in the app itself.
- qBittorrent search needs Python inside the qBittorrent container (most images include it) plus at least one search plugin.
- SABnzbd only uses scheduler changes after it restarts. The Scheduler page has a restart link.
