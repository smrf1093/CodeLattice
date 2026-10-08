---
name: react
description: React best practices for component design, hooks, state management, performance optimization, and project structure. Use when working with React or Next.js projects, or when the user asks about component patterns, hooks usage, or frontend architecture.
category: framework
domains:
  - react
  - typescript
  - javascript
  - frontend
  - nextjs
  - hooks
triggers:
  - "react"
  - "useState"
  - "useEffect"
  - "component"
  - "next.js"
  - "nextjs"
  - "JSX"
  - "TSX"
priority: 50
metadata:
  author: codelattice
  version: "1.0"
---

# React Best Practices

## Component Design

- **Single Responsibility**: each component does one thing.
- **Composition over inheritance**: use children and render props, not class inheritance.
- **Prefer function components** with hooks over class components.
- **Co-locate related code**: keep component, styles, types, and tests together.

```
components/
├── UserProfile/
│   ├── UserProfile.tsx      # Component
│   ├── UserProfile.test.tsx # Tests
│   ├── useUserProfile.ts    # Custom hook
│   └── index.ts             # Re-export
```

## Hooks

- **useState**: for local UI state. Keep state minimal — derive what you can.
- **useEffect**: for side effects (API calls, subscriptions). Always specify dependencies. Clean up in the return function.
- **useMemo / useCallback**: only when you have measured a performance problem. Don't optimize prematurely.
- **Custom hooks**: extract reusable stateful logic into `use*` functions.

```typescript
// Good: custom hook encapsulates data fetching
function useUser(id: string) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetchUser(id).then(data => {
      if (!cancelled) {
        setUser(data);
        setLoading(false);
      }
    });
    return () => { cancelled = true; };
  }, [id]);

  return { user, loading };
}
```

## State Management

- **Local state first**: `useState` for component-scoped state.
- **Lift state up**: when siblings need the same state, move it to their parent.
- **Context**: for truly global state (theme, auth, locale). Don't use Context for frequently-changing data.
- **External stores** (Zustand, Redux Toolkit): for complex shared state with many consumers.
- **Server state** (TanStack Query, SWR): for API data — don't manually cache in state.

## Performance

- **Avoid unnecessary re-renders**: split components so state changes are scoped.
- **React.memo**: wrap expensive pure components that receive stable props.
- **Virtualize long lists**: use `react-window` or `react-virtualized`.
- **Code splitting**: `React.lazy()` + `Suspense` for route-level splitting.
- **Keys**: always use stable, unique keys in lists — never array index.

## Patterns to Avoid

- **Prop drilling more than 2-3 levels** — use Context or composition instead.
- **useEffect for derived state** — compute it during render instead.
- **God components** — if a component has 200+ lines, split it.
- **Inline object/array literals in JSX** — they create new references every render.

```typescript
// Bad: derived state in useEffect
const [filteredItems, setFilteredItems] = useState([]);
useEffect(() => {
  setFilteredItems(items.filter(i => i.active));
}, [items]);

// Good: compute during render
const filteredItems = useMemo(
  () => items.filter(i => i.active),
  [items]
);
```

## TypeScript Integration

- Define prop types with `interface`, not `type` (for better error messages and extendability).
- Use `React.FC` sparingly — prefer explicit return types.
- Type events: `React.ChangeEvent<HTMLInputElement>`, `React.FormEvent`.
- Use discriminated unions for component variants.

## Testing

- Use React Testing Library — test behavior, not implementation.
- Query by role, label, or text — not by CSS class or test ID.
- Test user interactions: click, type, submit.
- Mock API calls, not internal hooks.
