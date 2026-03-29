import os
from app.core.database import SessionLocal
from app.services.stats import StatsService
from datetime import datetime

def test_stats():
    db = SessionLocal()
    
    print("Testing Monthly Stats:")
    monthly = StatsService.get_edge_stats(db, period="monthly")
    for s in monthly[:5]:
        print(f"Period: {s['label']}, Count: {s['event_count']}, Avg Gap: {s['avg_gap_pct']}%, Avg Fade: {s['avg_fade_pct']}%")
        
    print("\nTesting Weekly Stats:")
    weekly = StatsService.get_edge_stats(db, period="weekly")
    for s in weekly[:5]:
        print(f"Period: {s['label']}, Count: {s['event_count']}, Avg Gap: {s['avg_gap_pct']}%, Avg Fade: {s['avg_fade_pct']}%")
        
    print("\nTesting Distribution Data:")
    dist = StatsService.get_distribution_data(db)
    print(f"Total events in distribution: {len(dist['events'])}")
    if dist['events']:
        print(f"First event: {dist['events'][0]}")
        
    db.close()

if __name__ == "__main__":
    test_stats()
