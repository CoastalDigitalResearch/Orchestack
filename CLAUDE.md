# Coastal Digital Research — repository policy

This repository is owned by Coastal Digital Research (an anonymous LLC).
Agents and humans working here MUST follow these rules.

## Commit identity
- All commits MUST be authored as
  `Coastal Digital Research <hello@coastaldigitalresearch.com>`.
- NEVER author commits as Adam Pippert or any personal identity.
- NEVER use an identity containing `claude`/`anthropic`; no Claude
  `Co-Authored-By` trailers or "Generated with" footers.
- If git identity is unset or personal, fix it before committing:
  `git config user.name "Coastal Digital Research"` /
  `git config user.email "hello@coastaldigitalresearch.com"`

## Where code goes
- `origin` = Forgejo (`http://superrouter:3000/coastaldigitalresearch/Orchestack.git`)
  is the development remote: ALL day-to-day pushes, branches, and PRs go here only.
- `github` = `https://github.com/CoastalDigitalResearch/Orchestack.git` is a
  release-distribution mirror: push here ONLY for tagged releases or release-boundary
  main sync. NEVER push feature/dev branches to `github`.

## Where models & artifacts go
- Trained models, weights, and datasets publish to Hugging Face under the
  Coastal Digital Research org (`huggingface.co/CoastalDigitalResearch`), using CDR
  credentials. Never publish CDR artifacts under a personal account.

## Anonymity
- Do not add personal names, emails, or identifying metadata to commits, code,
  docs, model cards, or release notes. Public-facing authorship is always
  "Coastal Digital Research".
