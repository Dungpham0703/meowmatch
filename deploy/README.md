# Standalone EC2 deployment

This configuration runs MeowMatch, PostgreSQL/pgvector, and an Nginx reverse proxy on one EC2 instance. It uses a separate database and does not depend on the IELTS server or its domain.

Suggested starting configuration: Ubuntu 24.04, `t4g.small` (ARM64, 2 GiB RAM), a 20 GiB gp3 root disk, and one Elastic IP. An x86 `t3.small` is an alternative. For a demo, HTTP access is `http://ELASTIC_IP/`. This configuration does not provision an HTTPS certificate.

Create a security group for this instance with HTTP/80 open to intended visitors and SSH/22 restricted to the administrator's current IP. Do not expose PostgreSQL/5432 or API/8000; the compose stack does not publish those ports. Use IMDSv2 and encrypted EBS. Use standard CPU credits if avoiding surplus CPU credit charges is a priority.

## Prepare the server

Install Docker Engine and its Compose plugin using the official instructions for the chosen Ubuntu release. Clone the private GitHub repository using your own credentials; do not place a GitHub token in shell history or cloud-init user data.

From the original machine, copy the selected image files to the server. The image directory is intentionally excluded from Git:

```sh
rsync -av ./stickers/ ubuntu@ELASTIC_IP:~/meowmatch/stickers/
```

On the server:

```sh
cd ~/meowmatch
cp deploy/.env.example .env.ec2
openssl rand -hex 24
```

Edit `.env.ec2`, set a random hexadecimal `POSTGRES_PASSWORD`, and provide the Gemini key. Keep the password URL-safe because it is used in `DATABASE_URL`. Restrict this file to the administrator with `chmod 600 .env.ec2`.

## Start and seed

```sh
docker compose --env-file .env.ec2 -f deploy/compose.yml up -d --build --wait
```

To avoid recreating embeddings, transfer the existing cached vectors from the original machine directly into the API container's cache volume. The cache contains image vectors, not the Gemini key:

```sh
tar -C .cache/embeddings -cf - . | ssh ubuntu@ELASTIC_IP \
  'cd ~/meowmatch && docker compose --env-file .env.ec2 -f deploy/compose.yml exec -T api tar -xf - -C /app/.cache/embeddings'
```

Then seed the collection on the server:

```sh
docker compose --env-file .env.ec2 -f deploy/compose.yml exec -T api python seed_pgvector.py
curl --fail http://127.0.0.1/api/health
```

Confirm `sticker_count: 400`, `total_vectors: 400`, and `ready: true`, then test keyword and image semantic search through the public IP. Startup health checks confirm database connectivity; seeding is a separate step and readiness must be checked afterwards.

Without a transferred cache, seeding calls Gemini for missing image embeddings and observes the configured rate limit. Nginx limits search requests per IP and globally to reduce accidental quota exhaustion. The frontend receives HTTP 429 when the proxy limit is reached.

## Operate

```sh
docker compose --env-file .env.ec2 -f deploy/compose.yml ps
docker compose --env-file .env.ec2 -f deploy/compose.yml logs --tail=100 api web
```

PostgreSQL and embeddings use persistent Docker volumes. Back up the database, source image files, and secret configuration before rebuilding or deleting the instance. Stopping an instance does not release its Elastic IP or remove its EBS storage; those resources can continue to incur charges. Do not use `down -v` unless deliberately deleting the stored data.

A domain can be added later by pointing a new domain's DNS to the Elastic IP and configuring HTTPS. It does not need to share the IELTS domain.

## HTTPS hostname

The current live deployment also enables the [free HTTPS hostname configuration](HTTPS.md). When updating that deployment, include `-f deploy/compose.https.yml` after the base compose file so HTTPS remains enabled.
