# Deploying Entitled

> **There is no login.** Anyone who can open the URL can see and change every household, and move the shared demo clock. Use only the invented demo data on a public URL. Real data needs authentication first.

The backend (FastAPI, Chromium, OCR) and the frontend (Next.js) run as two containers. People only ever talk to the frontend, which passes `/api`, `/portal` and `/static` on to the backend.

| Option | Good for | Tested? |
|---|---|---|
| [Docker on your machine](#docker) | Running it anywhere with one command | Yes |
| [Tunnel](#share-it-with-a-tunnel) | A demo from your laptop, including the microphone on phones | No |
| [One server](#one-server) | A URL that stays up | Containers yes, server and HTTPS no |
| [Two hosting services](#two-hosting-services) | Platforms like Render, Railway, Fly or Vercel | Containers yes, platforms no |

## Environment

**No value is required.** With nothing set, it uses browser speech, on-device OCR, pattern matching and simulated SMS, which is the tested setup.

To add keys, copy `.env.example` to `.env`. It is gitignored and is never copied into an image. The optional keys are explained in that file. Their integrations have not been run against the live services, so run the whole journey before relying on one.

These matter when deploying:

| Variable | Set on | When | Default | Notes |
|---|---|---|---|---|
| `BACKEND_URL` | Frontend | **Build** | `http://backend:8000` | Fixed into the build. Changing it means rebuilding the frontend, and setting it at runtime does nothing. |
| `CONFIRMATION_SECRET` | Backend | Runtime | Generated once in the data folder | Set it if your data folder might be wiped. Changing it only cancels confirmations in progress. |
| `ENTITLED_DATA_DIR` | Backend | Runtime | `/data` in the image | Holds the database and form screenshots. It must be on a disk that survives restarts. |
| `PORT` | Either | Runtime | 8000 backend, 3000 frontend | For hosts that assign a port. Both images follow it. |

Generate a secret with:

```bash
openssl rand -hex 32
```

`DATABASE_URL` can point at PostgreSQL, but that path has not been tested and the image has no PostgreSQL driver. Keep SQLite and run **one backend instance only**. Each extra instance would run its own status poller, and SQLite lives on one disk.

## Docker

You need Docker with Compose 2.24 or newer. The first build takes about 4 minutes.

```bash
docker compose up -d --build --wait
```

Open <http://localhost:3000>. Only port 3000 is published, and the backend stays private inside Docker.

| Task | Command |
|---|---|
| See logs | `docker compose logs -f` |
| Stop, keeping data | `docker compose down` |
| Update | `git pull`, then `docker compose up -d --build --wait` |
| Back up data | `docker compose cp backend:/data ./entitled-backup` |
| **Reset to fresh demo data, deleting everything** | `docker compose down -v`, then `docker compose up -d --wait` |

Reset between demos, because the time-skip buttons move one clock shared by all households.

## Share it with a tunnel

With the app running on port 3000, a tunnel gives it a temporary HTTPS address. Microphones need HTTPS, so this also lets voice work on a phone. It uses [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/). Your machine has to stay on.

```bash
cloudflared tunnel --url http://localhost:3000
```

## One server

Use any Linux server with Docker, sized as shown [below](#how-big-a-server). Clone the repo, follow the [Docker](#docker) steps, then put an HTTPS proxy in front of port 3000. With Caddy and a domain pointing at the server, this is the whole config:

```
entitled.example.com {
    reverse_proxy localhost:3000
}
```

Allow ports 80 and 443 in the firewall, and don't open port 3000 to the internet. Docker's published ports can bypass firewalls such as `ufw`, so change the mapping in `docker-compose.yml` to `"127.0.0.1:3000:3000"`.

## Two hosting services

The backend goes on Render and the frontend on Vercel. **Deploy the backend first**, because the frontend needs its URL when it builds.

### Backend on Render

Render's free plan won't work: it has no disk and only 0.1 CPU, and Vercel gives up on a request after 120 s. [`render.yaml`](render.yaml) asks for 1 CPU, 2 GB and a 1 GB disk, about $25.25 a month by Render's published rates. Render shows the exact price before you confirm.

1. Open <https://render.com/deploy?repo=https://github.com/harshisingh777/entitled> and sign in.
2. Review the plan and price, then apply the Blueprint. The first build takes several minutes.
3. Copy the service's URL and check it:

```bash
curl https://your-backend.onrender.com/api/health
```

### Frontend on Vercel

From the repo root, sign in once, then deploy with your Render URL:

```bash
npx vercel login
```

```bash
npx vercel deploy frontend --prod --build-env BACKEND_URL=https://your-backend.onrender.com
```

Run the deploy command again after any frontend change. Vercel's free Hobby plan is for non-commercial use.

### Other hosts

| Setting | Backend | Frontend |
|---|---|---|
| Dockerfile | `backend/Dockerfile` | `frontend/Dockerfile` |
| Build context | Repo root, because it also needs `schemes/` | `frontend` |
| Build argument | | `BACKEND_URL=https://your-backend.example.com` |
| Disk | Persistent, mounted at `/data` | |
| Environment | `CONFIRMATION_SECRET`, plus any keys | |
| Health check | `/api/health` | |
| Instances | Exactly 1 | |

Choose a backend plan that allows the image size, about 2.7 GB. A host that sleeps when idle will make the first visitor wait, and without a persistent disk every restart returns to fresh demo data.

## How big a server

Measured with the whole journey on a laptop, limiting only the backend. Reading is the slowest step, and a cloud server's shared CPU may be slower.

| Backend limit | Slowest document read | Peak memory | Result |
|---|---|---|---|
| 2 CPU, 2 GB | 13 s | 544 MiB | Passed |
| 1 CPU, 1 GB | 37 s | 650 MiB | Passed |
| 1 CPU, 512 MB | 30 s | 512 MiB, the limit itself | Passed, with no margin |
| 0.5 CPU, 1 GB | 145 s | Not measured | One document read only, almost at the 150 s limit |

**Use 2 CPU and 2 GB for a demo. 1 CPU and 1 GB is the minimum.** The frontend adds about 80 MB. Documents read with a Sarvam key would run off the server, but that has not been measured.

## Check that it works

```bash
curl https://your-site.example.com/api/health
```

That should return `{"status":"ok"}`, which also proves the frontend reaches the backend. Then press **Walk through Kamla Devi's case** and go as far as the money landing. This covers OCR, the browser agent, the confirmation step and tracking, and it's the only way to know a host can run Chromium.

To run the automated journey and the screen-size checks against containers on the same machine, install the backend's requirements locally, then from `backend/`:

```bash
python scripts/ui_check.py
```

## If something goes wrong

| What you see | Likely cause | Fix |
|---|---|---|
| Pages load, but every action fails with a 500 | Wrong `BACKEND_URL`, or it was set after the build | Correct it and rebuild the frontend |
| Backend exits with `PermissionError` on `/data` | The image hands the disk to its app user at startup, and the host blocked that | Give user ID 10001 write access to the disk |
| Reading a document fails after 120 s on Vercel | The backend's CPU is too small | Use at least 1 CPU |
| Reading a document fails after 150 s | The server is too small | Use at least 1 CPU |
| Form filling fails | Not enough memory for Chromium, or `BACKEND_PORT` differs from the port in use | Check memory. Prefer setting `PORT` alone |
| Data disappears on restart | No persistent disk at `/data` | Attach one |
| Microphone does nothing | The page isn't on HTTPS or `localhost` | Use a tunnel or HTTPS |
| Port 3000 is already in use | Another copy of the app is running | Stop it first, or change the mapping in `docker-compose.yml` |

## What has been tested

These were run on a clean copy of the repo in Docker on Windows:

- The whole journey by tapping, and every screen at 7 sizes, with no layout problems or console errors.
- The pre-filled PDF and the form screenshots.
- Data and the signing secret surviving `docker compose down` and `up`.
- Three documents read at the same time.
- A host-assigned port on both containers.
- `.env` and local data staying out of the backend image.

A 5.9 MB photo was also uploaded through the app outside Docker. It was shrunk to 0.24 MB before sending and still read correctly.

These have **not** been tested:

- The latest backend image, which hands a host's disk to its app user at startup. Docker wouldn't start for this check.
- Any hosting platform, HTTPS proxy, Caddy or the tunnel.
- A real microphone.
- PostgreSQL.
- Any live API key.
