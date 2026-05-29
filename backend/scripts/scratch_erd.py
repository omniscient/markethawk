import os
import sys

sys.path.append(os.path.join(os.getcwd(), "backend"))

from app.core.database import Base
from app.models import *

for name, table in Base.metadata.tables.items():
    print(f"Table: {name}")
    for idx in table.indexes:
        print(f"  Index: {idx.name} cols: {[c.name for c in idx.columns]}")
