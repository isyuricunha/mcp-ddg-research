# Project TODO

## Milestone 1 - Repository skeleton

- [x] Create Python package metadata.
- [x] Add Docker and docker-compose scaffolding.
- [x] Add initial project to-do list.

## Milestone 2 - Core implementation

- [x] Add typed request and response models.
- [x] Add atomic JSON cache.
- [x] Add SSRF-safe URL validation.
- [x] Add DuckDuckGo search with HTML fallback.
- [x] Add safe webpage fetching and clean text extraction.
- [x] Add FastMCP server tools.

## Milestone 3 - Tests and validation

- [x] Add pytest coverage for search parsing and redirect handling.
- [x] Add pytest coverage for SSRF blocking.
- [x] Add pytest coverage for cache read/write behavior.
- [x] Add pytest coverage for HTML extraction cleanup.
- [x] Run lint, tests, package build, import checks, and Docker smoke checks.

## Milestone 4 - Release automation

- [x] Add GitHub Actions workflow for Python validation and semantic releases.
- [x] Add Docker Hub and GitHub Container Registry image publishing on release.
- [x] Document required release secrets and image tags.
- [x] Publish Docker images from explicit `v*` release tag pushes.
