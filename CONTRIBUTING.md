# Contributing

Contributions are welcome.

For optimization rules, please include:

1. a stable rule ID;
2. human-readable documentation under `docs/rules/`;
3. deterministic detection logic;
4. tests covering normal and exceptional cases;
5. no automatic mutation unless equivalence can later be validated on a clone.

Run tests with:

```bash
pytest
```
