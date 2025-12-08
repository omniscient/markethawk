# Stock Scanner System - Deployment Guide

## Overview
This guide provides comprehensive instructions for deploying the Stock Scanner System across different environments, from local development to production cloud deployment.

## Architecture Summary
- **Frontend**: React + Vite + TypeScript
- **Backend**: FastAPI + Python + PostgreSQL
- **Database**: PostgreSQL with Redis caching
- **Cloud**: AWS (primary) with Docker support

## Local Development Setup

### Prerequisites
- Docker & Docker Compose
- Node.js 18+ 
- Python 3.11+
- PostgreSQL 15+

### Quick Start with Docker Compose
```bash
# Clone the repository
git clone <repository-url>
cd stock-scanner-system

# Start all services
docker-compose up -d

# Access the application
# Frontend: http://localhost:3000
# Backend API: http://localhost:8000
# Database: localhost:5432
```

### Manual Setup

#### Backend Setup
```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export DATABASE_URL="postgresql://username:password@localhost/stockscanner"
export ENVIRONMENT="development"

# Run database migrations
alembic upgrade head

# Start the API server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

#### Frontend Setup
```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev

# Build for production
npm run build
```

## Cloud Deployment Options

### Option 1: AWS (Recommended)

#### Prerequisites
- AWS CLI configured
- SAM CLI installed
- Docker installed

#### Deployment Steps
```bash
# Build and deploy with SAM
sam build
sam deploy --guided

# Or use CloudFormation directly
aws cloudformation create-stack \
  --stack-name stock-scanner-prod \
  --template-body file://aws-deployment.yaml \
  --capabilities CAPABILITY_IAM
```

#### AWS Services Used
- **Lambda**: Backend API execution
- **RDS PostgreSQL**: Primary database (free tier)
- **ElastiCache Redis**: Caching layer
- **S3 + CloudFront**: Frontend hosting
- **API Gateway**: API management
- **EventBridge**: Scheduled scanning
- **Secrets Manager**: Secure credential storage

#### Cost Optimization
- Use AWS Free Tier services
- Configure auto-scaling for Lambda
- Use Spot instances for non-critical workloads
- Enable cost alerts and monitoring

### Option 2: Google Cloud Platform

#### Prerequisites
- GCP CLI configured
- Enable required APIs

#### Deployment
```bash
# Deploy to Cloud Run
gcloud run deploy stock-scanner-api \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated

# Deploy frontend to Firebase
firebase deploy
```

### Option 3: Azure

#### Prerequisites
- Azure CLI configured

#### Deployment
```bash
# Deploy to Azure Container Instances
az container create \
  --resource-group stock-scanner-rg \
  --name stock-scanner-api \
  --image stock-scanner:latest \
  --ports 8000
```

## Environment Configuration

### Development Environment
```bash
# .env.development
DATABASE_URL=postgresql://postgres:password@localhost:5432/stockscanner_dev
REDIS_URL=redis://localhost:6379/0
ENVIRONMENT=development
DEBUG=true
```

### Production Environment
```bash
# .env.production
DATABASE_URL=<production-database-url>
REDIS_URL=<redis-cluster-url>
ENVIRONMENT=production
DEBUG=false
SECRET_KEY=<secure-secret-key>
```

## Database Management

### Initial Setup
```sql
-- Create database
createdb stockscanner

-- Run migrations
alembic upgrade head

-- Load initial data
psql -d stockscanner -f database-seed.sql
```

### Backup Strategy
```bash
# Automated daily backups
0 3 * * * pg_dump stockscanner > backup_$(date +%Y%m%d).sql

# Upload to S3
aws s3 cp backup_*.sql s3://stockscanner-backups/
```

## Monitoring & Logging

### CloudWatch Configuration
```yaml
# CloudWatch dashboard
widgets:
  - type: metric
    properties:
      metrics:
        - AWS/Lambda/Invocations
        - AWS/Lambda/Duration
        - AWS/Lambda/Errors
      period: 300
```

### Health Checks
```bash
# API health check
curl -f http://localhost:8000/api/health

# Database connectivity
pg_isready -h localhost -p 5432 -U postgres
```

## Security Best Practices

### 1. Network Security
- Use VPC with private subnets
- Configure security groups properly
- Enable SSL/TLS encryption
- Use NAT Gateway for outbound traffic

### 2. Data Security
- Encrypt data at rest and in transit
- Use AWS Secrets Manager for credentials
- Implement proper access controls
- Regular security audits

### 3. Application Security
- Input validation and sanitization
- Rate limiting on API endpoints
- CORS configuration
- Regular dependency updates

## Scaling Considerations

### Horizontal Scaling
```yaml
# Lambda auto-scaling
ReservedConcurrentExecutions: 100
DeadLetterQueue:
  Type: SQS
  TargetArn: !GetAtt DeadLetterQueue.Arn
```

### Database Scaling
```sql
-- Read replicas for scaling
CREATE READ REPLICA stockscanner_read_replica;

-- Connection pooling
ALTER SYSTEM SET max_connections = 200;
```

### Caching Strategy
```python
# Redis caching decorators
@cache.memoize(timeout=300)
def get_stock_data(ticker):
    return fetch_from_yahoo_finance(ticker)
```

## Troubleshooting

### Common Issues

#### Database Connection
```bash
# Test database connection
psql -h <host> -U postgres -d stockscanner

# Check connection pool
SELECT * FROM pg_stat_activity;
```

#### API Performance
```bash
# Monitor API response times
curl -w "@curl-format.txt" -o /dev/null -s http://localhost:8000/api/health
```

#### Memory Issues
```bash
# Monitor memory usage
docker stats

# Check Lambda memory
aws logs filter-log-events --log-group-name /aws/lambda/stock-scanner-backend
```

## Maintenance

### Regular Tasks
1. **Daily**: Monitor alerts and system health
2. **Weekly**: Review performance metrics
3. **Monthly**: Update dependencies and security patches
4. **Quarterly**: Capacity planning and cost optimization

### Update Process
```bash
# Update dependencies
pip install -r requirements.txt --upgrade
npm update

# Run tests
pytest
npm test

# Deploy updates
sam deploy
```

## Cost Management

### AWS Cost Optimization
- Use Spot instances for non-critical workloads
- Configure auto-scaling policies
- Use reserved instances for predictable workloads
- Enable cost allocation tags

### Monitoring Costs
```bash
# Set up cost alerts
aws budgets create-budget \
  --account-id <account-id> \
  --budget-name "StockScanner-Monthly" \
  --budget-limit Amount=100,Unit=USD \
  --time-unit MONTHLY
```

## Support & Documentation

### Getting Help
- Check application logs
- Review CloudWatch metrics
- Consult troubleshooting guide
- Contact support team

### Documentation
- API documentation: `/docs` endpoint
- System architecture: `docs/architecture.md`
- User guide: `docs/user-guide.md`
- API reference: `docs/api-reference.md`

## Next Steps

1. **Performance Optimization**: Implement advanced caching strategies
2. **Feature Enhancement**: Add machine learning capabilities
3. **Integration**: Connect with external trading platforms
4. **Monitoring**: Implement advanced observability tools
5. **Scaling**: Prepare for enterprise-level deployment

## Conclusion

This deployment guide provides a comprehensive roadmap for deploying the Stock Scanner System across various environments. The modular architecture supports both small-scale deployments and enterprise-level implementations.

For additional support or questions, please refer to the documentation or contact the development team.