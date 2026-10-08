---
name: strategy-pattern
description: Strategy design pattern — encapsulate a family of algorithms and make them interchangeable. Use when you have multiple approaches to the same task, conditional logic selecting between algorithms, or need to swap behavior at runtime.
category: pattern
domains:
  - strategy
  - design-pattern
  - behavioral
  - polymorphism
  - algorithms
triggers:
  - "strategy pattern"
  - "design pattern"
  - "swap algorithm"
  - "interchangeable"
  - "if elif chain"
  - "conditional logic"
priority: 50
metadata:
  author: codelattice
  version: "1.0"
---

# Strategy Pattern

## When to Use

- You have multiple algorithms/approaches for the same operation
- You see long `if/elif/else` or `switch` chains selecting behavior
- You need to swap behavior at runtime without changing the caller
- Different clients need different implementations of the same interface

## Structure

```
Context  ─────uses─────▶  Strategy (interface)
                              │
                    ┌─────────┼─────────┐
                    ▼         ▼         ▼
               StrategyA  StrategyB  StrategyC
```

## Python Example

```python
from typing import Protocol

class PricingStrategy(Protocol):
    def calculate(self, base_price: float, quantity: int) -> float: ...

class RegularPricing:
    def calculate(self, base_price: float, quantity: int) -> float:
        return base_price * quantity

class BulkPricing:
    def calculate(self, base_price: float, quantity: int) -> float:
        if quantity >= 100:
            return base_price * quantity * 0.8  # 20% discount
        return base_price * quantity

class SeasonalPricing:
    def calculate(self, base_price: float, quantity: int) -> float:
        return base_price * quantity * 0.9  # 10% seasonal discount

# Context: uses strategy without knowing the concrete type
class OrderCalculator:
    def __init__(self, pricing: PricingStrategy):
        self.pricing = pricing

    def total(self, base_price: float, quantity: int) -> float:
        return self.pricing.calculate(base_price, quantity)

# Usage — strategy is injected, easily swappable
calculator = OrderCalculator(BulkPricing())
total = calculator.total(10.0, 150)
```

## TypeScript Example

```typescript
interface CompressionStrategy {
  compress(data: Buffer): Buffer;
  decompress(data: Buffer): Buffer;
}

class GzipCompression implements CompressionStrategy {
  compress(data: Buffer): Buffer { /* ... */ }
  decompress(data: Buffer): Buffer { /* ... */ }
}

class ZstdCompression implements CompressionStrategy {
  compress(data: Buffer): Buffer { /* ... */ }
  decompress(data: Buffer): Buffer { /* ... */ }
}

class FileProcessor {
  constructor(private compression: CompressionStrategy) {}

  save(data: Buffer, path: string): void {
    const compressed = this.compression.compress(data);
    fs.writeFileSync(path, compressed);
  }
}
```

## Strategy vs Other Patterns

| Pattern | Use When |
|---------|----------|
| **Strategy** | Multiple algorithms, swap at runtime |
| **Template Method** | Same algorithm structure, varying steps |
| **State** | Object behavior changes based on internal state |
| **Factory** | Creating objects, not selecting behavior |

## Code Smells That Suggest Strategy

- `if payment_type == "credit": ... elif payment_type == "paypal": ...`
- `switch (sortOrder) { case "date": ... case "name": ... }`
- Boolean flags that change behavior: `def process(data, use_fast_mode=False)`
- Functions with many conditional branches doing the same conceptual task

## Implementation Tips

- Use Protocol/interface for the strategy — not abstract base classes (more flexible).
- Register strategies in a dict for lookup by name: `strategies = {"bulk": BulkPricing(), "regular": RegularPricing()}`.
- In Python, simple strategies can be plain functions (callables are first-class).
- Combine with dependency injection for maximum flexibility.
