# Environment Variables Guide

This guide explains how to manage environment variables for the Stock Scanner System.

## 🔑 Quick Start

### 1. Create `.env` File

Create a file named `.env` in the project root directory:

```
c:\git\trading\OKComputer_Custom Stock Scanner System\.env
```

### 2. Add Your Variables

```bash
# Polygon.io API Key (Required)
POLYGON_API_KEY=your_polygon_api_key_here

# Optional: Override default database settings
# DATABASE_URL=postgresql://postgres:stockscanner123@postgres:5432/stockscanner

# Optional: Override default Redis settings
# REDIS_URL=redis://redis:6379/0

# Optional: Set environment
# ENVIRONMENT=development
```

### 3. Restart Containers

```bash
docker-compose down
docker-compose up -d
```

---

## 📋 Available Environment Variables

### Required Variables

| Variable | Description | Example | Used By |
|----------|-------------|---------|---------|
| `POLYGON_API_KEY` | Your Polygon.io API key for market data | `mhg7iNgqAkNDbuREK8Gl8Cqr7irfkoA9` | Backend, Celery |

### Optional Variables

| Variable | Description | Default | Used By |
|----------|-------------|---------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://postgres:stockscanner123@postgres:5432/stockscanner` | Backend, Celery |
| `REDIS_URL` | Redis connection string | `redis://redis:6379/0` | Backend, Celery |
| `ENVIRONMENT` | Environment mode | `development` | Backend |
| `SECRET_KEY` | Secret key for sessions/JWT | Auto-generated | Backend |

---

## 🔧 How It Works

### Docker Compose Integration

Your `docker-compose.yml` automatically reads from the `.env` file:

```yaml
environment:
  POLYGON_API_KEY: ${POLYGON_API_KEY:-}
  DATABASE_URL: postgresql://postgres:stockscanner123@postgres:5432/stockscanner
```

The `${POLYGON_API_KEY:-}` syntax means:
- Read `POLYGON_API_KEY` from `.env` file
- If not found, use empty string (the part after `:-`)

### Which Containers Use Which Variables?

```yaml
# Backend API
backend:
  environment:
    DATABASE_URL: postgresql://...
    POLYGON_API_KEY: ${POLYGON_API_KEY:-}
    ENVIRONMENT: development

# Celery Worker
celery-worker:
  environment:
    DATABASE_URL: postgresql://...
    POLYGON_API_KEY: ${POLYGON_API_KEY:-}
    REDIS_URL: redis://redis:6379/0

# Flower
flower:
  environment:
    CELERY_BROKER_URL: redis://redis:6379/0
    CELERY_RESULT_BACKEND: redis://redis:6379/0
```

---

## ✅ Verify Environment Variables

### Check if variables are loaded:

```bash
# Check backend container
docker exec stockscanner-api printenv POLYGON_API_KEY

# Check celery worker
docker exec stockscanner-celery printenv POLYGON_API_KEY

# View all environment variables in backend
docker exec stockscanner-api printenv
```

### Test API connection:

```bash
# Check backend health
curl http://localhost:8000/health

# View API docs (should show Polygon.io endpoints)
# Open: http://localhost:8000/docs
```

---

## 🔒 Security Best Practices

### ✅ DO:
- ✅ Use `.env` file for secrets (already in `.gitignore`)
- ✅ Keep different `.env` files for dev/staging/production
- ✅ Regenerate API keys if accidentally committed
- ✅ Use environment-specific values
- ✅ Document required variables in this file

### ❌ DON'T:
- ❌ Commit `.env` to version control (already prevented)
- ❌ Share `.env` files in chat/email
- ❌ Hardcode secrets in `docker-compose.yml`
- ❌ Use production keys in development
- ❌ Store `.env` in public locations

---

## 📝 Example `.env` File

### Development (Local)

```bash
# Polygon.io API Key
POLYGON_API_KEY=mhg7iNgqAkNDbuREK8Gl8Cqr7irfkoA9

# Environment
ENVIRONMENT=development

# Optional: Enable debug logging
# LOG_LEVEL=DEBUG
```

### Production (Example - DO NOT USE THESE VALUES)

```bash
# Polygon.io API Key (use production key)
POLYGON_API_KEY=prod_key_here

# Database (use managed database)
DATABASE_URL=postgresql://user:pass@prod-db.example.com:5432/stockscanner

# Redis (use managed Redis)
REDIS_URL=redis://prod-redis.example.com:6379/0

# Environment
ENVIRONMENT=production

# Security
SECRET_KEY=super_secret_production_key_here
```

---

## 🐛 Troubleshooting

### Problem: API key not working

**Check if variable is set:**
```bash
docker exec stockscanner-api printenv POLYGON_API_KEY
```

**If empty:**
1. Verify `.env` file exists in project root
2. Check `.env` file has correct format (no quotes needed)
3. Restart containers: `docker-compose down && docker-compose up -d`

### Problem: Changes to `.env` not reflected

**Solution:**
```bash
# Stop containers
docker-compose down

# Start containers (reads .env again)
docker-compose up -d
```

**Note:** Docker Compose only reads `.env` when containers start, not while running.

### Problem: "Invalid API key" errors

**Verify your key:**
1. Login to https://polygon.io/dashboard
2. Check your API key is active
3. Verify you're using the correct key (not the secret key)
4. Check your plan has access to required endpoints

### Problem: Can't find `.env` file

**Location:**
```
c:\git\trading\OKComputer_Custom Stock Scanner System\.env
```

**Create it:**
1. Open Notepad or VS Code
2. Create new file
3. Save as `.env` (with the dot at the beginning)
4. Make sure it's not saved as `.env.txt`

---

## 🔄 Updating Environment Variables

### Add New Variable

1. **Edit `.env` file:**
   ```bash
   NEW_VARIABLE=new_value
   ```

2. **Update `docker-compose.yml`** (if needed):
   ```yaml
   environment:
     NEW_VARIABLE: ${NEW_VARIABLE:-default_value}
   ```

3. **Restart containers:**
   ```bash
   docker-compose down
   docker-compose up -d
   ```

### Remove Variable

1. **Delete from `.env` file**
2. **Remove from `docker-compose.yml`** (if added)
3. **Restart containers**

---

## 📚 Additional Resources

### Polygon.io API
- Dashboard: https://polygon.io/dashboard
- API Docs: https://polygon.io/docs
- Pricing: https://polygon.io/pricing

### Docker Compose Environment Variables
- Official Docs: https://docs.docker.com/compose/environment-variables/

### Project Documentation
- [README.md](README.md) - Project overview
- [DEVELOPMENT.md](DEVELOPMENT.md) - Development setup and tools
- [docker-compose.yml](docker-compose.yml) - Container configuration

---

## 🎯 Common Use Cases

### Switching Between API Keys

```bash
# Development key
POLYGON_API_KEY=dev_key_here

# Production key (in separate .env.production)
POLYGON_API_KEY=prod_key_here
```

### Using Different Databases

```bash
# Local PostgreSQL
DATABASE_URL=postgresql://postgres:stockscanner123@postgres:5432/stockscanner

# Cloud PostgreSQL (AWS RDS example)
DATABASE_URL=postgresql://user:pass@mydb.abc123.us-east-1.rds.amazonaws.com:5432/stockscanner
```

### Multiple Environments

Create separate env files:
- `.env` - Development (local)
- `.env.staging` - Staging environment
- `.env.production` - Production environment

Load specific file:
```bash
docker-compose --env-file .env.staging up -d
```

---

**💡 Tip:** Keep this file updated as you add new environment variables to your project!
