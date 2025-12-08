# Stock Scanner System Architecture

## System Overview
Professional-grade stock scanner and alert system designed to identify pre-market volume spikes with specific criteria patterns.

## Core Components

### 1. Data Layer
- **Primary Data Source**: Yahoo Finance API (Free, reliable, comprehensive)
- **Backup Data Source**: Alpha Vantage API (Premium option for higher frequency)
- **Data Types**: Historical OHLCV, real-time quotes, volume data, company fundamentals
- **Update Frequency**: 
  - Historical data: Daily
  - Real-time data: 1-minute intervals during market hours
  - Pre-market data: 4:00 AM - 9:30 AM EST

### 2. Database Schema
```sql
-- Stock Universe Management
CREATE TABLE stock_universes (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    criteria JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Monitored Stocks
CREATE TABLE monitored_stocks (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    universe_id INTEGER REFERENCES stock_universes(id),
    added_date DATE NOT NULL,
    last_scanned TIMESTAMP,
    is_active BOOLEAN DEFAULT true
);

-- Volume Events (Scanner Results)
CREATE TABLE volume_events (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    event_date DATE NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    pre_market_volume BIGINT NOT NULL,
    avg_volume_20d BIGINT NOT NULL,
    relative_volume DECIMAL NOT NULL,
    volume_spike_ratio DECIMAL NOT NULL,
    price_change_pct DECIMAL NOT NULL,
    criteria_met JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Scanner Configuration
CREATE TABLE scanner_configs (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    criteria JSONB NOT NULL,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 3. Backend API (Python + FastAPI)
**Framework**: FastAPI (High performance, async support)
**Key Endpoints**:
- `POST /api/scanner/run` - Execute scanner on demand
- `GET /api/scanner/results` - Get scanner results
- `POST /api/universe/create` - Create stock universe
- `GET /api/universe/list` - List stock universes
- `POST /api/alerts/configure` - Configure alert settings
- `GET /api/stocks/historical/{ticker}` - Get historical data

### 4. Scanner Algorithm
**Criteria Logic**:
1. **Pre-market Volume Spike**: Volume > 4x 20-day average
2. **Low Volume Preceding Days**: Average volume < 0.5x 20-day average for last 3 days
3. **Price Movement**: Gap up > 1% from previous close
4. **Minimum Volume Threshold**: Pre-market volume > 100,000 shares
5. **Liquidity Filter**: Average daily volume > 500,000 shares

**Implementation**:
```python
def scan_pre_market_volume_spike(ticker):
    # Get historical data
    data = get_historical_data(ticker, period="30d")
    
    # Calculate metrics
    avg_volume_20d = data['volume'].rolling(20).mean()
    pre_market_volume = get_pre_market_volume(ticker)
    
    # Apply criteria
    volume_spike = pre_market_volume > (4 * avg_volume_20d.iloc[-1])
    low_preceding_volume = all(data['volume'].iloc[-4:-1] < (0.5 * avg_volume_20d.iloc[-1]))
    price_gap = get_gap_percentage(ticker) > 1.0
    
    return volume_spike and low_preceding_volume and price_gap
```

### 5. Frontend (React + Vite)
**Framework**: React 18 + Vite + TypeScript
**UI Components**:
- Real-time dashboard with stock scanner results
- Interactive charts showing volume patterns
- Alert configuration panel
- Stock universe management interface
- Historical event browser

**Styling**: Tailwind CSS with financial data visualization theme

### 6. Cloud Infrastructure
**Provider**: AWS Free Tier (Cost-effective)
**Services**:
- **Compute**: AWS Lambda (Scanner execution)
- **Database**: PostgreSQL on RDS Free Tier
- **Storage**: S3 for historical data
- **API Gateway**: For REST API endpoints
- **CloudWatch**: For monitoring and alerts
- **EventBridge**: For scheduled scanner execution

### 7. Deployment Strategy
**Backend**: Docker container with FastAPI
**Frontend**: Static hosting on S3 + CloudFront
**Database**: AWS RDS PostgreSQL
**CI/CD**: GitHub Actions for automated deployment

## Cost Optimization
- **Data Costs**: Start with Yahoo Finance (free), upgrade to paid APIs as needed
- **Cloud Costs**: AWS Free Tier covers initial usage
- **Database**: PostgreSQL free tier for development
- **Monitoring**: Basic CloudWatch metrics (free tier)

## Security Considerations
- API authentication using JWT tokens
- Rate limiting on API endpoints
- Encrypted database connections
- Secure storage of API keys in AWS Secrets Manager

## Scalability Plan
1. **Phase 1**: Single-threaded scanner, basic monitoring
2. **Phase 2**: Multi-threaded scanning, real-time alerts
3. **Phase 3**: Advanced analytics, machine learning integration
4. **Phase 4**: Enterprise features, white-label solutions