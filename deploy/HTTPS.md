# Free HTTPS hostname

The current demo uses **https://meowmatch.3.104.167.1.sslip.io**. The hostname is a subdomain supplied by [sslip.io](https://sslip.io/), not a separately registered domain owned by this project. It automatically resolves to the embedded Elastic IP. No domain registration or Route 53 hosted zone was purchased.

HTTPS uses a free Let's Encrypt certificate. Certbot runs on the EC2 host and its systemd timer renews the certificate automatically. A deployment hook reloads Nginx after successful renewal. The certificate directory is mounted read-only in Nginx; private keys are not in Git or the application image.

## Enable on a deployment

First deploy the HTTP stack as described in [README.md](README.md). Ensure that the chosen hostname resolves to the EC2 public IP and that its security group permits TCP ports 80 and 443. Then, from the repository directory on the EC2 instance:

```sh
bash deploy/enable-https.sh meowmatch.3.104.167.1.sslip.io
```

The script installs Certbot, enables HTTP-01 validation, obtains the certificate, writes `SITE_ADDRESS` into the private `.env.ec2`, and enables the HTTPS compose overlay. It registers the ACME account without an email address and agrees to the CA's terms as part of obtaining the requested certificate. The DNS hostname is validated before use.

Keep the HTTPS overlay in subsequent deployment commands:

```sh
docker compose --env-file .env.ec2 -f deploy/compose.yml -f deploy/compose.https.yml up -d --build --wait
```

HTTP requests for the hostname redirect to HTTPS; direct HTTP access by IP remains available. Keyword/image search limits apply to both entry points, sharing the global limit.

## Verify renewal

```sh
sudo certbot certificates
sudo systemctl status certbot.timer
sudo certbot renew --dry-run --run-deploy-hooks
```

The renewal dry run and Nginx reload hook were verified on the live instance. The certificate issued during setup expires on 2027-02-15 and is expected to renew automatically before then.

The free hostname and certificate add no registration or certificate fees. EC2, storage, public IPv4, traffic, and Gemini usage keep their existing pricing. The free hostname depends on the DNS provider and the embedded IP; an owned domain can replace it later with the same setup procedure.
