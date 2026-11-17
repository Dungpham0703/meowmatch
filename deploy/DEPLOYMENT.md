# Current MeowMatch deployment

- URL: **http://3.104.167.1** (direct HTTP access by Elastic IP)
- AWS region: `ap-southeast-2` (Sydney)
- EC2: `meowmatch-prod`, instance `i-0db54d1dc7c4e84b7`
- Instance type: `t4g.small` (ARM64, 2 vCPU, 2 GiB RAM), standard CPU credits
- Storage: encrypted 20 GiB gp3 root volume
- Stack: MeowMatch API, PostgreSQL/pgvector, and Nginx on the same instance
- Collection: 400 English meme metadata records, 400 cached image vectors
- Application source deployed: `580bc8e`

The IELTS instance is a separate instance. This deployment does not use its domain, database, or application configuration.

## Access and operation

The SSH key and runtime secrets are on the original workstation under the ignored `.cache/ec2/` directory, not in GitHub. From the repository directory on that workstation:

```sh
ssh -i .cache/ec2/meowmatch.pem ubuntu@3.104.167.1
```

SSH is restricted to the administrator IP used during setup. If that IP changes, update the SSH source rule on the MeowMatch security group through AWS before connecting. HTTP/80 is public; PostgreSQL/5432 and API/8000 are not published.

On the instance:

```sh
cd ~/meowmatch
docker compose --env-file .env.ec2 -f deploy/compose.yml ps
docker compose --env-file .env.ec2 -f deploy/compose.yml logs --tail=100 api web
```

Services restart automatically with Docker after a reboot. Source and images were transferred directly from the workstation; the deployment directory is an extracted source snapshot rather than a Git checkout. The original workstation's ignored `.cache/ec2/state.json` records the provisioned resources for administration.

## Cost estimate

At the AWS On-Demand prices queried during deployment, a 730-hour month is approximately:

| Resource | Estimate |
| --- | ---: |
| t4g.small at $0.0212/hour | $15.48 |
| 20 GiB gp3 at $0.096/GiB-month | $1.92 |
| One public IPv4 / Elastic IP at $0.005/hour | $3.65 |
| Total | **$21.05/month** |

This is an estimate before taxes, data transfer, Gemini usage, and any AWS credits. EBS and the Elastic IP can remain billable when the instance is stopped. See the [operating guide](README.md) before rebuilding or deleting persistent data.

## Verified

The app, database, and proxy started successfully on ARM64. All 400 existing image vectors were restored from cache. Both keyword and image semantic search returned live results, and browser checks passed through the public IP for English UI/content, two search methods, desktop/mobile/tablet layouts, dialogs, keyboard tabs, API failures, and stale responses. AWS system and instance checks were healthy.
