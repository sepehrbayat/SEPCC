---
name: route-task
description: Choose the FCC model tier for a task using `.fcc/router.yml`.
---

# Route Task

Use `.fcc/router.yml`:

- trivial: haiku alias
- balanced: sonnet alias
- deep: opus alias

Keep routing inside FCC. Do not add another default routing proxy. If exact upstream model names are unknown, keep aliases and let FCC/provider config resolve them.
