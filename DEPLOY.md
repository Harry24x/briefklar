# Deploying BriefKlar

Architecture: **frontend on Vercel** (free Hobby plan) → **backend + PostgreSQL/pgvector + Caddy
on one Ubuntu VM** (Docker Compose, automatic HTTPS). You run every command yourself; never
paste keys or passwords into chats or commits.

Why one VM: the backend loads PyTorch, the embedding model and the re-ranker (~1.5 GB RAM).
Free "web service" tiers with 512 MB RAM (e.g. Render) are too small.

| Option | Cost | Notes |
|---|---|---|
| **Oracle Cloud Always Free**, Ampere A1 (2 OCPU, 12 GB RAM, ARM64) | free for the life of the account | needs a credit card for identity verification only |
| Azure for Students, B2s VM (2 vCPU, 4 GB) | uses the student credit, which runs out | no card; stop the VM when not needed |

### Staying at 0 € on Oracle

- **Never click "Upgrade to Pay As You Go".** An Always Free account cannot be charged; only an
  upgraded account can. A temporary verification hold on the card at sign-up is removed again.
- Only create resources with the **Always Free-eligible** label: one A1.Flex VM with at most
  2 OCPU / 12 GB (the A1 limit was halved in August 2026), one boot volume of 50 GB.
- If the VM is idle for 7 days (CPU p95 < 20 %), Oracle may **reclaim** (stop/delete) it. That
  costs nothing; you just create it again and redo steps 3–6. The code and data can always be
  rebuilt from GitHub and the crawl.

The steps below are the same for both once you have an Ubuntu VM with a public IP.

---

## 1. Create the VM (Oracle)

1. Oracle Cloud console → **Compute → Instances → Create instance**.
2. Image: **Canonical Ubuntu 24.04** (or 22.04). Shape: **Ampere → VM.Standard.A1.Flex**,
   **2 OCPU / 12 GB** (check the "Always Free-eligible" label). Boot volume: default (~47 GB).
   If you get "out of capacity", try another availability domain, or retry later (A1 capacity
   is often full; early morning usually works better).
3. Networking: keep "Assign a public IPv4 address". Add your **SSH public key**.
4. After it starts, note the **public IP**.

### Open ports 80 and 443

Oracle has two firewalls:

- **Security list** (console): Networking → Virtual cloud networks → your VCN → Security
  lists → Default → **Add ingress rules**: source `0.0.0.0/0`, TCP, destination port `80`;
  same again for `443`.
- **On the VM** (Ubuntu images on Oracle block ports with iptables):

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

## 2. Free domain for HTTPS

Let's Encrypt needs a domain name. Free option: **duckdns.org** (log in with GitHub) →
create e.g. `briefklar` → set its IP to your VM's public IP → your API domain is
`briefklar.duckdns.org`.

## 3. Install Docker on the VM

```bash
ssh ubuntu@<PUBLIC_IP>
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
exit   # log out and in again so the group change applies
ssh ubuntu@<PUBLIC_IP>
docker version   # must show a "Server:" section
```

## 4. Get the code and configure `.env`

```bash
git clone https://github.com/Harry24x/briefklar.git
cd briefklar
cp .env.example .env
nano .env
```

Set at least:

| Variable | Value |
|---|---|
| `POSTGRES_PASSWORD` | a long random password: `openssl rand -hex 24` |
| `DATABASE_URL` | not needed in production (Compose sets it) |
| `GROQ_API_KEY` | your Groq key |
| `API_DOMAIN` | e.g. `briefklar.duckdns.org` |
| `CORS_ORIGINS` | your Vercel URL, e.g. `https://briefklar.vercel.app` (add it after step 7) |

```bash
chmod 600 .env
```

## 5. Start

```bash
docker compose --env-file .env -f infra/docker-compose.prod.yml up -d --build
docker compose --env-file .env -f infra/docker-compose.prod.yml ps
```

The first build takes ~10 minutes (PyTorch for ARM64). All three services should be `running`
(`db` also `healthy`).

## 6. First ingest and model warm-up

```bash
# crawl the official sources into the database (~5 min, polite: 1 request/second)
docker compose --env-file .env -f infra/docker-compose.prod.yml exec backend python -m app.ingest.crawl

# download both models once, so the first user request is not slow
docker compose --env-file .env -f infra/docker-compose.prod.yml exec backend \
  python -c "from app.rag.embed import get_model; from app.rag.retrieve import get_reranker; get_model(); get_reranker(); print('models ready')"

curl https://<API_DOMAIN>/health     # {"status":"ok"}
```

## 7. Frontend on Vercel

1. vercel.com → **Add New → Project** → import `Harry24x/briefklar`.
2. **Root Directory:** `frontend`. Framework: Next.js (detected).
3. **Environment variable:** `NEXT_PUBLIC_API_URL` = `https://<API_DOMAIN>` (no trailing slash).
4. Deploy. Then put the Vercel URL into `CORS_ORIGINS` on the VM and restart the backend:

```bash
nano .env   # CORS_ORIGINS=https://<your-project>.vercel.app
docker compose --env-file .env -f infra/docker-compose.prod.yml up -d backend
```

5. Fill in the placeholders on the **Impressum** and **Privacy** pages
   (`frontend/src/app/impressum/page.tsx`, `frontend/src/app/privacy/page.tsx`) before you share
   the link. A public website in Germany needs an Impressum.

## 8. Updating

```bash
cd ~/briefklar && git pull
docker compose --env-file .env -f infra/docker-compose.prod.yml up -d --build
```

## Troubleshooting

| Problem | Check |
|---|---|
| Caddy has no certificate | DuckDNS IP correct? Ports 80/443 open in **both** firewalls? `docker compose ... logs caddy` |
| `CORS` error in the browser | `CORS_ORIGINS` contains the exact Vercel URL (https, no trailing slash); backend restarted |
| `/ask` very slow the first time | run the warm-up command from step 6 |
| `429` from the API | daily limit per IP (20 questions, 5 letters) or Groq's free rate limit |
