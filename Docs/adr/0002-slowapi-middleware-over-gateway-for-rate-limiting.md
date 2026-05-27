# SlowAPI middleware over a dedicated gateway for rate limiting

We chose `slowapi` ASGI middleware over a reverse proxy (Nginx, Traefik, Caddy) to implement API rate limiting on the FastAPI backend.

A reverse proxy rejects connections at the socket layer before Python processes them, which is materially better under an adversarial connection flood — the kernel drops packets before Uvicorn burns CPU. However, every concrete threat this decision addresses is self-inflicted: a developer's automation loop exhausting the Polygon.io API quota, saturating the DB connection pool, or flooding the Celery queue. For self-inflicted threats a 429 from middleware is just as effective as a 429 from a proxy — the automation receives the error and backs off. There are no external adversaries because MarketHawk is a single-tenant internal tool.

SlowAPI also covers a blind spot that a gateway cannot: Celery workers fire Polygon calls directly, bypassing any proxy entirely. Throttling scan submission at the API layer is the only lever for Polygon quota exhaustion. A gateway-only approach would leave this threat unaddressed.

The trade-off is that under a true connection flood — if the deployment ever becomes internet-facing — middleware is the weaker option because Uvicorn still accepts each TCP connection. If MarketHawk ever becomes multi-tenant or internet-facing, we should add a reverse proxy in front *in addition to* the middleware (defense in depth, complementary roles). The two layers are not mutually exclusive.
