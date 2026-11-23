# Rules for this repository

This repository is public. Anyone can read its code, its commit history and its Actions run logs.

## 1. English only

- Write everything in English: code, comments, docstrings, workflow names and input descriptions,
  log and error messages, README and other docs, commit messages, branch names and pull requests.
- Non-English text is allowed only where a value must match an external system exactly
  (for example a currency code or an API field), never as prose.

## 2. Never store personal data

- Do not commit personal data of anyone: names, email addresses, phone numbers, addresses,
  account or ID numbers, bank details, usernames or nicknames of real people, IP addresses,
  location, chat messages, or screenshots that show any of these.
- Do not commit secrets or anything that identifies a private deployment: tokens, API keys,
  passwords, ntfy topics, Worker URLs or subdomains, `.env` files. Use GitHub Actions secrets
  or repository variables instead.
- Do not commit data files, exports, caches or logs. Fetched data (prices, P2P ads and their
  advertisers, notes) goes to the Worker, never into this repo.
- Run logs are public too: print counts and status only, never fetched records, push text,
  tokens or URLs from variables.
- Example values in code and docs must be obviously fake (`<subdomain>`, `example.com`).
- Commit with the GitHub noreply email address, not a personal one.
- Before every commit, check the diff for anything above. If personal data was ever committed,
  removing it in a new commit is not enough: the history must be rewritten.
