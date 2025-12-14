# Project Structure

This document provides a high-level overview of the codebase structure to assist with context understanding.

```
stock-scanner-system/
├── backend/
│   ├── alembic/                # Database migrations (Alembic)
│   ├── app/
│   │   ├── core/               # Core config, DB, Celery app
│   │   ├── models/             # SQLAlchemy models
│   │   ├── routers/            # FastAPI route handlers
│   │   ├── schemas/            # Pydantic schemas (request/response)
│   │   ├── services/           # Business logic
│   │   ├── main.py             # App factory
│   │   └── tasks.py            # Celery tasks
│   ├── tests/                  # Pytest tests
│   ├── alembic.ini             # Alembic configuration
│   ├── requirements.txt        # Python dependencies
│   ├── Dockerfile              # Backend container definition
│   └── run.py                  # Entry point script
├── frontend/
│   ├── src/
│   │   ├── api/                # API client layer
│   │   ├── components/         # React components
│   │   ├── pages/              # Route pages/views
│   │   ├── App.tsx             # Main React app
│   │   └── main.tsx            # Entry point
│   ├── package.json            # Node dependencies
│   └── Dockerfile              # Frontend container definition
├── database-schema.sql         # Legacy SQL schema (reference only, use Alembic)
├── docker-compose.yml          # Local development orchestration
├── README.md                   # Main documentation
├── DEVELOPMENT.md              # Dev guide & troubleshooting
├── ENV_VARIABLES.md            # Environment variable reference
└── system-architecture.md      # Detailed system design doc
```

## Key Directories

### `backend/app`
The core FastAPI application. Structured to separate concerns:
- **Routers**: Handle HTTP requests and routing.
- **Services**: Contain the actual business logic (scanning, data fetching).
- **Models**: Database definitions.
- **Schemas**: Data validation and serialization.

### `frontend/src`
React application using functional components and hooks.
- **Components**: Reusable UI elements.
- **Pages**: Top-level views corresponding to routes.
- **API**: Centralized API call definitions.
