---
description: test the functions
---

Goal: Ensure data integrity and factor correctness.
1. Scope: Test critical paths, boundary conditions (Market Open/Close).
2. Data: Generate realistic mock data (including gaps & outliers).
3. Precision: Use `decimal.Decimal` for PnL verification where critical.
4. Continuity: Verify index/datetime alignment and null counts.