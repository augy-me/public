# Public
Rules for contributing: see [CLAUDE.md](CLAUDE.md).

GitHub Actions runners for sources that refuse Cloudflare. A Cloudflare Worker starts each run; the run proves itself
with its OIDC token, asks the Worker what to fetch and posts the answers back.

- [binance/](binance/): Binance spot and P2P prices, `.github/workflows/binance.yml`.
- [bls/](bls/): the US CPI index (BLS, FRED as fallback), `.github/workflows/bls.yml`.
- [ntfy/](ntfy/): sends queued ntfy notes, `.github/workflows/ntfy.yml`.
- [common/](common/): shared HTTP helpers (OIDC token, Worker URL and headers) and the job runner.
