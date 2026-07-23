# Private conversational assistant design

## Runtime

```text
Telegram or stable CLI identity
  → central identity registry
  → private user SQLite file
  → relevant memories + recent conversation
  → conversational LLM
  → fixed, validated memory/finance tools
  → private user SQLite file
```

Normal chat requires no tool. The model calls tools only when it needs durable memory or authoritative financial data.

## Storage boundary

The central registry contains only `provider`, `external_id`, opaque `user_key`, and creation time. External IDs never become filenames.

Each user file has a deliberately small stable envelope:

- profile
- transactions
- category limits
- flexible memories
- conversation turns
- pending confirmations
- processed message IDs

Memory details are bounded JSON, so new personal facts do not require schema migrations. The LLM cannot create tables, run SQL, choose database paths, or supply a user key.

## Money boundary

Amounts use integer minor units. Transactions are the source of truth. Totals and remaining category budgets are derived at query time.

- Expected pocket money → memory
- Pocket money received → transaction
- Category maximum/limit → configured limit
- Largest category spend → historical maximum transaction

Deletes and forgetting always require confirmation. Large writes use `AGENT_CONFIRM_AMOUNT_THRESHOLD`.

## Memory

Memories are explicit facts, events, preferences, or goals with learned and optional occurred timestamps. SQLite FTS5 searches every active memory, then lexical relevance, salience, and recency choose the few sent to the model.

Each request also receives the latest eight conversational turns and up to three relevant snippets from the previous 30 days. Ordinary user/assistant chat older than 90 days is pruned while the latest eight turns, transactions, durable memories, and tool events remain.

No graph or vector database is used. Add embeddings only after measured FTS/lexical recall failures.

## Privacy limits

Separate files prevent accidental cross-user queries and simplify per-user backup/deletion. They do not protect data from an attacker who controls the host. Use encrypted disks or SQLCipher only when the threat model requires host-level encryption.
