# Stock Scanner System

A professional-grade stock scanner and alert system designed to identify pre-market volume spikes and unusual trading patterns. Built with modern web technologies and deployed on cloud infrastructure.

## 🚀 Features

### Core Functionality
- **Pre-Market Volume Spike Detection**: Identifies stocks with volume spikes >4x average
- **Low Volume Preceding Days**: Scans for low volume periods before spikes
- **Price Gap Analysis**: Detects significant price gaps with volume confirmation
- **Real-time Alerts**: Configurable alert system with multiple delivery methods
- **Stock Universe Management**: Create and manage custom stock scanning universes
- **Historical Analysis**: Track and analyze scanner performance over time

### Technical Features
- **Modern Architecture**: React frontend with FastAPI backend
- **Real-time Data**: Polygon.io integration with professional market data
- **Scalable Design**: Cloud-native architecture supporting high throughput
- **Professional UI**: Financial-grade user interface with dark theme
- **API-first Design**: RESTful API with comprehensive documentation

## 📊 Scanner Criteria

The system identifies stocks meeting the following criteria:

1. **Pre-market Volume Spike**: Volume > 4x 20-day average
2. **Low Volume Preceding Days**: Average volume < 0.5x for last 3 days  
3. **Price Gap**: Gap up > 1% from previous close
4. **Minimum Volume**: Pre-market volume > 100,000 shares
5. **Liquidity Filter**: Average daily volume > 500,000 shares

## 🛠 Technology Stack

### Backend
- **Framework**: FastAPI (Python)
- **Database**: PostgreSQL with SQLAlchemy ORM
- **Caching**: Redis for performance optimization
- **Data Source**: Polygon.io API (Professional market data)
- **Task Queue**: Celery for background processing
- **Async Support**: AsyncPG, HTTPX for high-performance async operations

### Frontend
- **Framework**: React 18 with TypeScript
- **Build Tool**: Vite for fast development
- **Styling**: Tailwind CSS with custom financial theme
- **Charts**: Recharts for data visualization
- **State Management**: React Query for server state

### Infrastructure
- **Cloud**: AWS (Lambda, RDS, S3, CloudFront)
- **Containerization**: Docker with multi-stage builds
- **Orchestration**: Docker Compose for local development
- **CI/CD**: GitHub Actions for automated deployment

## 🏗 Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   React Frontend│    │   FastAPI       │    │   PostgreSQL    │
│   + Vite        │◄──►│   Backend       │◄──►│   Database      │
│   + TypeScript  │    │   + Python      │    │   + Redis       │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                │
                                ▼
                       ┌─────────────────┐
                       │   Polygon.io    │
                       │   Market Data   │
                       └─────────────────┘
```

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- Node.js 18+
- Python 3.11+
- PostgreSQL 15+

### Local Development
```bash
# Clone the repository
git clone https://github.com/yourusername/stock-scanner-system.git
cd stock-scanner-system

# Start with Docker Compose
docker-compose up -d

# Access the application
# Frontend: http://localhost:3000
# Backend API: http://localhost:8000
# API Docs: http://localhost:8000/docs

# Management Tools
# pgAdmin (PostgreSQL): http://localhost:5050
# Flower (Celery): http://localhost:5555
```

> **📖 For detailed setup and connection instructions, see [DEVELOPMENT.md](DEVELOPMENT.md)**


### Manual Setup
```bash
# Backend setup
cd backend
pip install -r requirements.txt
uvicorn main:app --reload

# Frontend setup  
cd frontend
npm install
npm run dev
```

## 📱 User Interface

### Dashboard
- Real-time scanner metrics and statistics
- Interactive charts showing volume spike trends
- Recent alerts and events feed
- Market status and scanner performance

### Scanner Configuration
- Multiple scanner types and criteria
- Real-time parameter adjustment
- Scan history and performance tracking
- Export and import scanner configurations

### Stock Universes
- Create custom stock scanning universes
- Define criteria-based stock selection
- Manage multiple universes for different strategies
- Import/export universe configurations

### Alert Management
- Configure multiple alert delivery methods
- Real-time notification system
- Alert history and performance tracking
- Customizable alert conditions

## 🔧 Configuration

### Environment Variables
```bash
# Database
DATABASE_URL=postgresql://user:pass@host:5432/stockscanner

# Market Data API
POLYGON_API_KEY=your-polygon-api-key

# Redis (optional)
REDIS_URL=redis://localhost:6379/0

# Environment
ENVIRONMENT=development|production

# Security
SECRET_KEY=your-secret-key
```

### Scanner Parameters
```json
{
  "pre_market_hours": {"start": "04:00", "end": "09:30"},
  "min_pre_market_volume": 100000,
  "min_avg_daily_volume": 500000,
  "volume_spike_threshold": 4.0,
  "low_volume_threshold": 0.5,
  "min_gap_percentage": 1.0
}
```

## 📊 API Documentation

### Endpoints
- `GET /api/scanner/run` - Execute scanner on demand
- `GET /api/scanner/results` - Get scanner results
- `POST /api/universe/create` - Create stock universe
- `GET /api/stocks/historical/{ticker}` - Get historical data
- `GET /api/health` - Health check

### Example API Call
```bash
curl -X POST http://localhost:8000/api/scanner/run \
  -H "Content-Type: application/json" \
  -d '{
    "scanner_type": "pre_market_volume",
    "tickers": ["AAPL", "GOOGL", "TSLA"]
  }'
```

## 🌐 Deployment

### AWS Deployment (Recommended)
```bash
# Deploy with SAM
sam build
sam deploy --guided

# Or use CloudFormation
aws cloudformation create-stack \
  --stack-name stock-scanner-prod \
  --template-body file://aws-deployment.yaml
```

### Docker Deployment
```bash
# Production build
docker-compose -f docker-compose.prod.yml up -d

# Scale services
docker-compose up -d --scale backend=3
```

## 📈 Performance

### Optimization Features
- **Caching Layer**: Redis for frequently accessed data
- **Database Indexing**: Optimized queries for fast retrieval
- **Async Processing**: Non-blocking API operations
- **CDN Integration**: Global content delivery
- **Connection Pooling**: Efficient database connections

### Benchmarks
- Scanner execution: ~2.3 seconds for 500 stocks
- API response time: <100ms for most endpoints
- Database queries: <50ms with proper indexing
- Frontend load time: <2 seconds

## 🔒 Security

### Security Features
- **Data Encryption**: SSL/TLS for data in transit
- **Authentication**: JWT-based API authentication
- **Input Validation**: Comprehensive data sanitization
- **Rate Limiting**: API request throttling
- **CORS Protection**: Cross-origin request security

### Best Practices
- Environment-specific configuration
- Secret management with AWS Secrets Manager
- Regular security audits and updates
- Network isolation with VPCs
- Encrypted data storage

## 📊 Monitoring

### Metrics Tracked
- Scanner execution time and success rate
- API response times and error rates
- Database performance and connection health
- System resource utilization
- Alert delivery success rates

### Logging
- Structured logging with correlation IDs
- Error tracking and alerting
- Performance monitoring
- Audit trails for compliance

## 🎯 Use Cases

### Day Traders
- Identify pre-market momentum stocks
- Volume spike alerts for entry points
- Historical pattern analysis

### Swing Traders
- Multi-day volume accumulation detection
- Breakout pattern identification
- Risk management alerts

### Algorithmic Traders
- API integration for automated strategies
- Custom scanner criteria development
- Backtesting data provision

### Financial Institutions
- Market monitoring and surveillance
- Client alert services
- Research and analysis tools

## 🚀 Roadmap

### Short-term (Q1 2024)
- [ ] Machine learning integration for pattern recognition
- [ ] Real-time websocket connections
- [ ] Mobile application development
- [ ] Advanced charting capabilities

### Medium-term (Q2-Q3 2024)
- [ ] Multi-asset class support (options, crypto)
- [ ] Social sentiment integration
- [ ] Advanced backtesting framework
- [ ] White-label enterprise solution

### Long-term (Q4 2024+)
- [ ] AI-powered trading signal generation
- [ ] Institutional-grade compliance features
- [ ] Global market expansion
- [ ] Advanced risk management tools

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

### Development Process
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests and documentation
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **Polygon.io**: For providing professional-grade market data
- **FastAPI**: For the excellent web framework
- **React Community**: For the powerful frontend ecosystem
- **Financial Markets**: For providing endless opportunities for analysis

## 📞 Support

- **Documentation**: Check the `/docs` endpoint for API documentation
- **Issues**: Report bugs via GitHub Issues
- **Discussions**: Join our community discussions
- **Email**: support@stockscanner.com

---

**⚠️ Disclaimer**: This tool is for educational and research purposes only. Not financial advice. Trading involves substantial risk of loss.

**🚀 Built with passion for financial markets and cutting-edge technology**