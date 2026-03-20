# Hints

Use `hint()` in notebooks to provide progressive hints as collapsed accordions:

```python
from mograder.runtime import hint

# Single hint — accordion label is "Hint"
hint("Think about what preserves insertion order")

# Multiple hints — numbered "Hint 1", "Hint 2", ...
hint(
    "Think about which data structure preserves insertion order",
    "Consider using `collections.OrderedDict`",
    "Use `OrderedDict.move_to_end()`"
)
```

Hints are rendered as `<details>` / `<summary>` accordions, so students must actively expand them. This encourages attempting the problem before seeking help.
