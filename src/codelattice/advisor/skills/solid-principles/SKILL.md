---
name: solid-principles
description: SOLID principles for object-oriented design — Single Responsibility, Open/Closed, Liskov Substitution, Interface Segregation, and Dependency Inversion. Use when reviewing code architecture, refactoring classes, or designing new modules.
category: principle
domains:
  - solid
  - architecture
  - refactoring
  - oop
  - design
  - clean-code
triggers:
  - "single responsibility"
  - "open closed"
  - "liskov"
  - "interface segregation"
  - "dependency inversion"
  - "SOLID"
  - "SRP"
  - "OCP"
  - "LSP"
  - "ISP"
  - "DIP"
priority: 50
metadata:
  author: codelattice
  version: "1.0"
---

# SOLID Principles

## S — Single Responsibility Principle (SRP)

A class/module should have one reason to change. If you can describe what it does with "and", it probably does too much.

**Signs of violation:**
- Class has methods that serve different stakeholders
- Changes to one feature require modifying unrelated code
- Class name includes "Manager", "Handler", "Processor", "Utils" (red flags for god objects)

**How to fix:**
- Extract each responsibility into its own class/module
- Group by what changes together, not by technical layer

```python
# Bad: UserService handles auth AND email AND profile
class UserService:
    def authenticate(self, credentials): ...
    def send_welcome_email(self, user): ...
    def update_profile(self, user, data): ...

# Good: separate concerns
class AuthService:
    def authenticate(self, credentials): ...

class EmailService:
    def send_welcome_email(self, user): ...

class ProfileService:
    def update_profile(self, user, data): ...
```

## O — Open/Closed Principle (OCP)

Software entities should be open for extension but closed for modification. Add new behavior by adding new code, not changing existing code.

**How to apply:**
- Use inheritance/composition to extend behavior
- Use strategy pattern or plugin systems
- Prefer configuration over code changes

```python
# Bad: modify existing code for each new payment type
def process_payment(payment_type, amount):
    if payment_type == "credit":
        ...
    elif payment_type == "paypal":
        ...
    # Must modify this function for every new type!

# Good: extend via new classes
class PaymentProcessor(Protocol):
    def process(self, amount: Decimal) -> bool: ...

class CreditCardProcessor:
    def process(self, amount): ...

class PayPalProcessor:
    def process(self, amount): ...
```

## L — Liskov Substitution Principle (LSP)

Subtypes must be substitutable for their base types without altering correctness. If `B` extends `A`, anywhere `A` is used, `B` should work without surprises.

**Signs of violation:**
- Subclass throws exceptions the parent doesn't
- Subclass ignores or overrides parent behavior in breaking ways
- Type checks like `isinstance()` before calling methods

**Rule of thumb:** If it looks like a duck but needs batteries, it violates LSP.

```python
# Bad: Square violates Rectangle's contract
class Rectangle:
    def set_width(self, w): self.width = w
    def set_height(self, h): self.height = h

class Square(Rectangle):
    def set_width(self, w):
        self.width = self.height = w  # Surprising!

# Good: separate types or use composition
class Shape(Protocol):
    def area(self) -> float: ...
```

## I — Interface Segregation Principle (ISP)

Don't force clients to depend on interfaces they don't use. Prefer many small, focused interfaces over one large one.

**How to apply:**
- Split fat interfaces into role-specific ones
- Use Protocol classes (Python) or interfaces (TypeScript) for each capability

```python
# Bad: one fat interface
class Worker(Protocol):
    def code(self): ...
    def test(self): ...
    def deploy(self): ...
    def manage_team(self): ...

# Good: role-specific interfaces
class Coder(Protocol):
    def code(self): ...

class Tester(Protocol):
    def test(self): ...

class Deployer(Protocol):
    def deploy(self): ...
```

## D — Dependency Inversion Principle (DIP)

High-level modules should not depend on low-level modules. Both should depend on abstractions. Abstractions should not depend on details.

**How to apply:**
- Depend on protocols/interfaces, not concrete classes
- Inject dependencies via constructor parameters
- Use dependency injection frameworks for large applications

```python
# Bad: high-level depends on low-level
class OrderService:
    def __init__(self):
        self.db = PostgresDatabase()  # Concrete dependency!
        self.email = SmtpEmailSender()  # Concrete dependency!

# Good: depend on abstractions
class OrderService:
    def __init__(self, db: Database, email: EmailSender):
        self.db = db
        self.email = email
```

## When to Apply SOLID

- **Refactoring**: when a class becomes hard to modify or test
- **Code review**: flag violations early before they compound
- **New design**: apply from the start for modules expected to evolve
- **Don't over-apply**: SOLID is a guideline, not a law. A 20-line script doesn't need dependency injection.
