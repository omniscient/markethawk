# MarketHawk Demo Sandbox

`make demo` starts a credential-free MarketHawk stack with deterministic sample data.

The demo uses Docker Compose project `markethawk_demo` and demo-only volumes:

- `markethawk_demo_postgres_data`
- `markethawk_demo_redis_data`
- `markethawk_demo_prometheus_multiproc`

Every `make demo` run resets those demo volumes. It does not touch normal development or live MarketHawk volumes.

Demo login:

- Username: `demo`
- Password: `markethawk-demo`
