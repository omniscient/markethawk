# Development Guide

This guide provides instructions for managing and monitoring your local development environment.

## 🛠 Management Tools

The Docker setup includes three management tools for monitoring and managing your data services:

| Tool | Purpose | Access URL | Credentials |
|------|---------|------------|-------------|
| **pgAdmin** | PostgreSQL Database Management | http://localhost:5050 | Email: `admin@stockscanner.com`<br>Password: `admin123` |
| **Flower** | Celery Task Monitoring | http://localhost:5555 | No authentication required |
| **RedisInsight** | Redis Cache Management | Install separately | See instructions below |

## 🚀 Quick Start

### Start All Services
```bash
# First time setup: Create .env file with your API keys
# See ENV_VARIABLES.md for details

# Start all containers including management tools
docker-compose up -d

# Check all services are running
docker-compose ps
```

> **🔑 API Keys Required:** Before starting, create a `.env` file with your Polygon.io API key. See [ENV_VARIABLES.md](ENV_VARIABLES.md) for detailed instructions.

### Access Management Tools
- **pgAdmin**: http://localhost:5050
- **Flower**: http://localhost:5555
- **API Documentation**: http://localhost:8000/docs
- **Frontend**: http://localhost:3000

---

## 📊 PostgreSQL Management with pgAdmin

### Initial Setup

1. **Access pgAdmin**
   - Navigate to http://localhost:5050
   - Login with:
     - Email: `admin@stockscanner.com`
     - Password: `admin123`

2. **Add PostgreSQL Server**
   - Right-click **Servers** → **Register** → **Server**
   
3. **Configure Connection**
   
   **General Tab:**
   - Name: `Stock Scanner DB` (or any name you prefer)
   
   **Connection Tab:**
   - Host name/address: `postgres` (Docker service name)
   - Port: `5432`
   - Maintenance database: `stockscanner`
   - Username: `postgres`
   - Password: `stockscanner123`
   - Save password: ✓ (optional, for convenience)

4. **Save and Connect**
   - Click **Save**
   - The server should now appear in the left sidebar

### Common Tasks

#### View Tables
1. Expand: **Servers** → **Stock Scanner DB** → **Databases** → **stockscanner** → **Schemas** → **public** → **Tables**
2. Right-click any table → **View/Edit Data** → **All Rows**

#### Run SQL Queries
1. Right-click **stockscanner** database → **Query Tool**
2. Write your SQL query
3. Click **Execute** (F5) or click the play button

#### Example Queries
```sql
-- View all stock universes
SELECT * FROM stock_universes ORDER BY created_at DESC;

-- View recent scanner results
SELECT * FROM scanner_results 
WHERE created_at > NOW() - INTERVAL '7 days'
ORDER BY created_at DESC;

-- Check database size
SELECT pg_size_pretty(pg_database_size('stockscanner'));

-- View active connections
SELECT * FROM pg_stat_activity;
```

#### Export Data
1. Right-click table → **Import/Export**
2. Toggle **Export** option
3. Choose format (CSV, JSON, etc.)
4. Click **OK**

#### Backup Database
1. Right-click **stockscanner** database → **Backup**
2. Choose filename and location
3. Select format (Custom recommended)
4. Click **Backup**

---

## 🌸 Celery Monitoring with Flower

### Access Flower Dashboard

1. **Navigate to Flower**
   - URL: http://localhost:5555
   - No authentication required in development

### Dashboard Overview

#### **Tasks Tab**
- View all Celery tasks (active, scheduled, completed, failed)
- Monitor task execution time
- See task arguments and results
- Retry failed tasks

#### **Workers Tab**
- Monitor active Celery workers
- View worker status and statistics
- Check worker configuration
- Manage worker pool

#### **Broker Tab**
- Monitor Redis broker connection
- View queue statistics
- Check message rates

#### **Monitor Tab**
- Real-time task execution monitoring
- Live task success/failure rates
- Task timeline visualization

### Common Tasks

#### View Active Tasks
1. Click **Tasks** tab
2. Filter by state: `ACTIVE`, `SUCCESS`, `FAILURE`, `PENDING`

#### Retry Failed Task
1. Go to **Tasks** tab
2. Find failed task
3. Click task ID
4. Click **Retry** button

#### Monitor Task Performance
1. Click **Monitor** tab
2. View real-time task execution graph
3. Check task throughput and latency

#### Shutdown Worker
1. Go to **Workers** tab
2. Select worker
3. Click **Shutdown** (use with caution)

### Example Background Tasks

Your system includes these Celery tasks:
- **Universe stock refresh**: Updates stock data for universes
- **Pre-market scans**: Runs volume spike detection
- **Data synchronization**: Syncs with Polygon.io API

---

## 🔴 Redis Management with RedisInsight

### Installation

RedisInsight is not containerized by default. Install it separately:

1. **Download RedisInsight**
   - Visit: https://redis.com/redis-enterprise/redis-insight/
   - Download Windows installer
   - Install and launch

2. **Add Redis Connection**
   - Click **Add Redis Database**
   - Connection Type: **Standalone**
   - Host: `localhost`
   - Port: `6379`
   - Database Alias: `Stock Scanner Redis`
   - Click **Add Redis Database**

### Common Tasks

#### Browse Keys
1. Click **Browser** tab
2. View all keys organized by pattern
3. Click any key to view its value

#### Monitor Commands
1. Click **Profiler** tab
2. Start profiling
3. View real-time Redis commands

#### View Memory Usage
1. Click **Analysis Tools**
2. Run memory analysis
3. View key size distribution

#### Execute Redis Commands
1. Click **CLI** tab
2. Run Redis commands directly

#### Example Redis Commands
```redis
# View all keys
KEYS *

# Get cache value
GET stock:AAPL:price

# View key TTL
TTL stock:AAPL:price

# View all Celery tasks
KEYS celery-task-meta-*

# Monitor real-time commands
MONITOR

# View Redis info
INFO

# Check memory usage
MEMORY USAGE stock:AAPL:price
```

---

## 🐳 Docker Management

### Useful Docker Commands

```bash
# View running containers
docker-compose ps

# View logs for specific service
docker-compose logs -f backend
docker-compose logs -f celery-worker
docker-compose logs -f flower
docker-compose logs -f pgadmin

# Restart specific service
docker-compose restart backend
docker-compose restart celery-worker

# Stop all services
docker-compose down

# Stop and remove volumes (⚠️ deletes data)
docker-compose down -v

# Rebuild containers
docker-compose up -d --build

# View resource usage
docker stats

# Access container shell
docker exec -it stockscanner-api bash
docker exec -it stockscanner-db psql -U postgres -d stockscanner
docker exec -it stockscanner-redis redis-cli
```

### Container Health Checks

```bash
# Check backend health
curl http://localhost:8000/health

# Check Redis connection
docker exec -it stockscanner-redis redis-cli ping

# Check PostgreSQL connection
docker exec -it stockscanner-db psql -U postgres -d stockscanner -c "SELECT 1;"

# Check Celery worker status
docker exec -it stockscanner-celery celery -A app.main.celery inspect active
```

---

## 🔍 Troubleshooting

### pgAdmin Issues

**Problem: Can't connect to PostgreSQL**
- ✅ Ensure you're using `postgres` as hostname (not `localhost`)
- ✅ Check containers are running: `docker-compose ps`
- ✅ Verify credentials match docker-compose.yml

**Problem: pgAdmin won't start**
- ✅ Check port 5050 is not in use
- ✅ View logs: `docker-compose logs pgadmin`
- ✅ Remove volume and restart: `docker volume rm okcomputer_custom-stock-scanner-system_pgadmin_data`

### Flower Issues

**Problem: No workers visible**
- ✅ Check celery-worker is running: `docker-compose ps`
- ✅ Verify Redis connection
- ✅ Check worker logs: `docker-compose logs celery-worker`

**Problem: Tasks not appearing**
- ✅ Ensure tasks are being triggered
- ✅ Check Celery configuration in backend
- ✅ Verify Redis broker URL is correct

### Redis Issues

**Problem: Can't connect with RedisInsight**
- ✅ Ensure Redis container is running
- ✅ Check port 6379 is exposed
- ✅ Use `localhost` (not `redis`) when connecting from host machine

### General Issues

**Problem: Containers won't start**
```bash
# Check for port conflicts
netstat -ano | findstr :5432  # PostgreSQL
netstat -ano | findstr :6379  # Redis
netstat -ano | findstr :5050  # pgAdmin
netstat -ano | findstr :5555  # Flower

# View detailed logs
docker-compose logs

# Restart everything
docker-compose down
docker-compose up -d
```

---

## 📚 Additional Resources

### Documentation Links
- [pgAdmin Documentation](https://www.pgadmin.org/docs/)
- [Flower Documentation](https://flower.readthedocs.io/)
- [RedisInsight Documentation](https://docs.redis.com/latest/ri/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [Celery Documentation](https://docs.celeryproject.org/)

### Keyboard Shortcuts

**pgAdmin:**
- `F5` - Execute query
- `F7` - Execute current statement
- `Ctrl+Space` - Auto-complete

**Flower:**
- No special shortcuts, web-based interface

---

## 🔐 Security Notes

> [!WARNING]
> **Development Credentials**
> 
> The credentials in this setup are for **local development only**. Never use these in production:
> - pgAdmin: `admin@stockscanner.com` / `admin123`
> - PostgreSQL: `postgres` / `stockscanner123`

> [!CAUTION]
> **Production Deployment**
> 
> Before deploying to production:
> 1. Change all default passwords
> 2. Use environment variables for secrets
> 3. Enable authentication on Flower
> 4. Use SSL/TLS for all connections
> 5. Restrict network access with firewalls

---

## 💡 Tips & Best Practices

### Performance Optimization
- Use pgAdmin's **Explain** feature to analyze slow queries
- Monitor Celery task execution times in Flower
- Check Redis memory usage regularly
- Index frequently queried columns in PostgreSQL

### Data Management
- Regularly backup your PostgreSQL database
- Monitor Redis memory usage (default: no eviction)
- Archive old scanner results to prevent database bloat
- Use pgAdmin's maintenance tools for vacuum and analyze

### Development Workflow
1. Use Flower to monitor background tasks during development
2. Use pgAdmin to inspect database state and run ad-hoc queries
3. Use RedisInsight to debug caching issues
4. Check Docker logs when services behave unexpectedly

---

**Happy Developing! 🚀**
