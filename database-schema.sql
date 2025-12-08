-- Stock Scanner System Database Schema
-- PostgreSQL Implementation

-- Enable UUID extension for unique identifiers
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Stock Universe Management
CREATE TABLE stock_universes (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    criteria JSONB NOT NULL, -- JSON object containing universe selection criteria
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT true,
    created_by VARCHAR(100) DEFAULT 'system'
);

-- Monitored Stocks Table
CREATE TABLE monitored_stocks (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    company_name VARCHAR(200),
    sector VARCHAR(100),
    industry VARCHAR(100),
    market_cap BIGINT,
    universe_id INTEGER REFERENCES stock_universes(id) ON DELETE CASCADE,
    added_date DATE NOT NULL,
    last_scanned TIMESTAMP,
    scan_count INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT true,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Volume Events Table (Scanner Results)
CREATE TABLE volume_events (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE,
    ticker VARCHAR(10) NOT NULL,
    event_date DATE NOT NULL,
    event_type VARCHAR(50) NOT NULL, -- 'pre_market_spike', 'volume_surge', etc.
    
    -- Volume Metrics
    pre_market_volume BIGINT NOT NULL,
    regular_volume BIGINT,
    avg_volume_20d BIGINT NOT NULL,
    avg_volume_50d BIGINT,
    relative_volume DECIMAL NOT NULL,
    volume_spike_ratio DECIMAL NOT NULL,
    
    -- Price Metrics
    previous_close DECIMAL NOT NULL,
    pre_market_high DECIMAL,
    pre_market_low DECIMAL,
    opening_price DECIMAL,
    closing_price DECIMAL,
    price_change_pct DECIMAL,
    price_gap_pct DECIMAL,
    
    -- Criteria Met (JSON object with boolean flags)
    criteria_met JSONB NOT NULL,
    
    -- Additional Context
    news_count INTEGER DEFAULT 0,
    earnings_date DATE,
    market_cap_at_event BIGINT,
    
    -- Metadata
    raw_data JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Scanner Configuration Table
CREATE TABLE scanner_configs (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    scanner_type VARCHAR(50) NOT NULL, -- 'pre_market_volume', 'volume_spike', etc.
    
    -- Scanner Parameters (JSON configuration)
    parameters JSONB NOT NULL,
    
    -- Criteria Configuration
    criteria JSONB NOT NULL, -- Array of criteria objects
    
    -- Execution Settings
    is_active BOOLEAN DEFAULT true,
    run_frequency VARCHAR(20), -- 'on_demand', 'hourly', 'daily', 'pre_market'
    last_run TIMESTAMP,
    next_run TIMESTAMP,
    
    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    created_by VARCHAR(100) DEFAULT 'system'
);

-- Alert Configuration Table
CREATE TABLE alert_configs (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    
    -- Alert Type and Conditions
    alert_type VARCHAR(50) NOT NULL, -- 'volume_spike', 'price_movement', etc.
    conditions JSONB NOT NULL,
    
    -- Delivery Settings
    delivery_method VARCHAR(50) NOT NULL, -- 'email', 'webhook', 'dashboard'
    delivery_config JSONB NOT NULL,
    
    -- Status and Metadata
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    created_by VARCHAR(100) DEFAULT 'system'
);

-- Alert History Table
CREATE TABLE alert_history (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE,
    alert_config_id INTEGER REFERENCES alert_configs(id) ON DELETE CASCADE,
    volume_event_id INTEGER REFERENCES volume_events(id) ON DELETE CASCADE,
    
    -- Alert Details
    alert_type VARCHAR(50) NOT NULL,
    ticker VARCHAR(10) NOT NULL,
    alert_date TIMESTAMP NOT NULL,
    
    -- Delivery Status
    delivery_status VARCHAR(20) NOT NULL, -- 'pending', 'sent', 'failed', 'delivered'
    delivery_attempts INTEGER DEFAULT 0,
    last_attempt TIMESTAMP,
    
    -- Response Data
    response_data JSONB DEFAULT '{}'::jsonb,
    error_message TEXT,
    
    created_at TIMESTAMP DEFAULT NOW()
);

-- Scanner Execution Log Table
CREATE TABLE scanner_execution_log (
    id SERIAL PRIMARY KEY,
    uuid UUID DEFAULT uuid_generate_v4() UNIQUE,
    scanner_config_id INTEGER REFERENCES scanner_configs(id) ON DELETE CASCADE,
    
    -- Execution Details
    execution_type VARCHAR(20) NOT NULL, -- 'scheduled', 'manual', 'api_triggered'
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    
    -- Results
    stocks_scanned INTEGER DEFAULT 0,
    events_detected INTEGER DEFAULT 0,
    errors_encountered INTEGER DEFAULT 0,
    
    -- Performance Metrics
    execution_duration_ms INTEGER,
    memory_usage_mb DECIMAL,
    
    -- Status and Logs
    status VARCHAR(20) NOT NULL, -- 'running', 'completed', 'failed', 'cancelled'
    error_log TEXT,
    
    created_at TIMESTAMP DEFAULT NOW()
);

-- Market Data Cache Table (for performance optimization)
CREATE TABLE market_data_cache (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    data_type VARCHAR(50) NOT NULL, -- 'historical', 'intraday', 'options'
    
    -- Data Storage
    data JSONB NOT NULL,
    data_hash VARCHAR(64) NOT NULL,
    
    -- Cache Management
    expires_at TIMESTAMP NOT NULL,
    last_accessed TIMESTAMP DEFAULT NOW(),
    access_count INTEGER DEFAULT 0,
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- User Preferences Table (for frontend customization)
CREATE TABLE user_preferences (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL,
    
    -- Dashboard Preferences
    dashboard_layout JSONB DEFAULT '{}'::jsonb,
    default_universe_id INTEGER REFERENCES stock_universes(id),
    
    -- Alert Preferences
    alert_settings JSONB DEFAULT '{}'::jsonb,
    notification_settings JSONB DEFAULT '{}'::jsonb,
    
    -- UI Preferences
    theme VARCHAR(20) DEFAULT 'light',
    language VARCHAR(10) DEFAULT 'en',
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Create Indexes for Performance
CREATE INDEX idx_monitored_stocks_ticker ON monitored_stocks(ticker);
CREATE INDEX idx_monitored_stocks_universe ON monitored_stocks(universe_id);
CREATE INDEX idx_monitored_stocks_active ON monitored_stocks(is_active);

CREATE INDEX idx_volume_events_ticker ON volume_events(ticker);
CREATE INDEX idx_volume_events_date ON volume_events(event_date);
CREATE INDEX idx_volume_events_type ON volume_events(event_type);
CREATE INDEX idx_volume_events_relative_vol ON volume_events(relative_volume);

CREATE INDEX idx_market_data_cache_ticker ON market_data_cache(ticker);
CREATE INDEX idx_market_data_cache_type ON market_data_cache(data_type);
CREATE INDEX idx_market_data_cache_expires ON market_data_cache(expires_at);

CREATE INDEX idx_scanner_execution_log_status ON scanner_execution_log(status);
CREATE INDEX idx_scanner_execution_log_start_time ON scanner_execution_log(start_time);

-- Create Views for Common Queries
CREATE VIEW active_monitored_stocks AS
SELECT * FROM monitored_stocks WHERE is_active = true;

CREATE VIEW recent_volume_events AS
SELECT * FROM volume_events 
WHERE event_date >= CURRENT_DATE - INTERVAL '30 days';

CREATE VIEW scanner_performance_stats AS
SELECT 
    scanner_config_id,
    COUNT(*) as total_runs,
    AVG(execution_duration_ms) as avg_duration_ms,
    SUM(events_detected) as total_events,
    SUM(errors_encountered) as total_errors
FROM scanner_execution_log 
WHERE status = 'completed'
GROUP BY scanner_config_id;

-- Insert Default Scanner Configuration
INSERT INTO scanner_configs (name, description, scanner_type, parameters, criteria) VALUES 
('Pre-Market Volume Spike Scanner', 
 'Detects stocks with significant pre-market volume spikes following low-volume periods',
 'pre_market_volume',
 '{
    "pre_market_hours": {"start": "04:00", "end": "09:30"},
    "min_pre_market_volume": 100000,
    "min_avg_daily_volume": 500000,
    "volume_spike_threshold": 4.0,
    "low_volume_threshold": 0.5,
    "low_volume_days": 3,
    "min_gap_percentage": 1.0,
    "max_gap_percentage": 20.0
 }'::jsonb,
 '[
    {
        "name": "pre_market_volume_spike",
        "description": "Pre-market volume exceeds 4x 20-day average",
        "condition": "pre_market_volume > (avg_volume_20d * 4)"
    },
    {
        "name": "low_volume_preceding_days",
        "description": "Volume was low in preceding 3 days",
        "condition": "volume_last_3_days < (avg_volume_20d * 0.5)"
    },
    {
        "name": "price_gap_up",
        "description": "Stock gaps up at least 1%",
        "condition": "gap_percentage >= 1.0"
    },
    {
        "name": "minimum_liquidity",
        "description": "Average daily volume exceeds 500K",
        "condition": "avg_volume_20d >= 500000"
    }
 ]'::jsonb
);

-- Insert Default Stock Universe
INSERT INTO stock_universes (name, description, criteria) VALUES 
('SPY Components', 
 'S&P 500 ETF components with high liquidity',
 '{
    "index": "SPY",
    "min_market_cap": 1000000000,
    "min_avg_volume": 1000000,
    "exchanges": ["NYSE", "NASDAQ"]
 }'::jsonb
);