---
name: django
description: Django best practices for project structure, views, models, forms, URLs, middleware, and the admin. Use when working with Django projects or when the user asks about Django architecture, ORM patterns, or web application design in Python.
category: framework
domains:
  - django
  - python
  - orm
  - web
  - rest-api
triggers:
  - "django"
  - "manage.py"
  - "django views"
  - "django models"
  - "django forms"
  - "django admin"
  - "django rest framework"
  - "DRF"
priority: 50
depends-on:
  - solid-principles
metadata:
  author: codelattice
  version: "1.0"
---

# Django Best Practices

## Project Structure

Follow the standard Django app layout. Each app should own one domain concept:

```
project/
├── config/               # Project-level settings, URLs, WSGI/ASGI
│   ├── settings/
│   │   ├── base.py       # Shared settings
│   │   ├── local.py      # Development overrides
│   │   └── production.py # Production overrides
│   ├── urls.py           # Root URL configuration
│   └── wsgi.py
├── apps/
│   ├── users/            # One app per domain
│   │   ├── models.py
│   │   ├── views.py
│   │   ├── serializers.py
│   │   ├── urls.py
│   │   ├── admin.py
│   │   ├── tests/
│   │   └── services.py   # Business logic (not in views!)
│   └── orders/
└── manage.py
```

## Views

- Keep views thin — they handle HTTP, not business logic.
- Extract business logic into `services.py` or domain-specific modules.
- Use class-based views (CBVs) for CRUD, function-based views (FBVs) for custom logic.
- For DRF: use `ViewSet` for full CRUD, `APIView` for custom endpoints.

```python
# Good: thin view, logic in service
class OrderCreateView(CreateAPIView):
    serializer_class = OrderSerializer

    def perform_create(self, serializer):
        order_service.create_order(
            user=self.request.user,
            **serializer.validated_data,
        )
```

## Models

- One model per database table. Don't put business logic in models.
- Use `Meta.constraints` and `Meta.indexes` for data integrity.
- Prefer `related_name` on all ForeignKey/ManyToMany fields.
- Use `choices` with `TextChoices`/`IntegerChoices` enums (not raw strings).
- Custom managers for reusable query patterns:

```python
class ActiveManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)

class Order(models.Model):
    objects = models.Manager()
    active = ActiveManager()
```

## QuerySet Best Practices

- Use `select_related()` for FK joins and `prefetch_related()` for M2M.
- Avoid N+1 queries — profile with `django-debug-toolbar`.
- Use `.only()` / `.defer()` for large tables.
- Use `F()` expressions for atomic updates: `Order.objects.filter(pk=1).update(count=F('count') + 1)`.
- Use `Q()` objects for complex filters.

## Forms and Serializers

- Validate at the serializer/form level, not in views.
- Use `validate_<field>` methods for field-level validation.
- Use `validate()` for cross-field validation.

## URLs

- Use `path()` with named URL patterns.
- Namespace apps: `app_name = "orders"` and `{% url 'orders:detail' pk=order.pk %}`.
- DRF: use `DefaultRouter` for ViewSets.

## Middleware

- Keep middleware lightweight — it runs on every request.
- Use `process_request` for pre-processing, `process_response` for post-processing.
- For per-view logic, prefer decorators or mixins over middleware.

## Testing

- Use `pytest-django` with `@pytest.mark.django_db`.
- Use `factory_boy` for test data, not fixtures.
- Test views via the test client, services via direct calls.
- Use `override_settings` for configuration-dependent tests.

## Security

- Always use `@login_required` or `IsAuthenticated` permission.
- Use Django's CSRF protection — don't disable it.
- Validate all user input through forms/serializers.
- Use `get_object_or_404()` instead of raw `.get()`.
