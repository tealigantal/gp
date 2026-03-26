# GP Assistant v2 Architecture

Single spine:

- `gateway/`: FastAPI entry and lane queue
- `runtime/`: authoritative turn loop (`parse -> evidence -> judgment -> reply -> commit`)
- `memory/`: session state, transcript, claim memory
- `book/`: daybook + 5m pulse + actionable board
- `judgment/`: recommend / follow-up / compare / exit
- `evidence/`: market, validation, portfolio, universe services
- `selection_engine/`: existing heavy ranking engine retained only as low-level daily selection builder

Truth model:

- `SessionState`: conversational truth
- `MarketBook`: intraday market truth
- `AdviceRun`: published truth

Time model:

- user turn => `runtime.turn_loop.run_turn_sync`
- market pulse => `book.engine.ensure_book` / `gp-assistant pulse`
