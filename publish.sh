#!/usr/bin/env bash
# Publish the NCE release: create the public GitHub repo and turn on Pages.
#
# ---------------------------------------------------------------------------
# THIS SCRIPT DOES NOT RUN ITSELF. It is staged and ready, and is deliberately
# NOT executed: the paper is inside the ARR October double-blind review window
# (submitted 2026-10-12 AoE; reviews open 2026-11-16), and the user asked that
# everything be prepared but nothing published until they say go.
#
# When the user is ready, run exactly this:
#
#     ./publish.sh
#
# Environment expected on the machine that runs it:
#   * GH_TOKEN, a token for the GitHub account below (repo scope)
#   * `gh`, the GitHub CLI, on PATH
#
# What it does, in order:
#   1. sanity-checks the token belongs to the expected account
#   2. refuses to run if the target repo already exists (no accidental clobber)
#   3. runs the leak scan and aborts on any finding
#   4. creates a PUBLIC repo from this working tree only
#   5. pushes and enables GitHub Pages on docs/, so the site lands at
#      https://<account>.github.io/<repo>/
#
# The repo name below must match the one the README badge, the site footer,
# CITATION.cff and the film's title card all print. Change it in one place and
# change those too.
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ACCOUNT="dengyl20"
REPO_NAME="native-context-editing"
AUTHOR_NAME="Yunlong Deng"
AUTHOR_EMAIL="dengyl20@users.noreply.github.com"

: "${GH_TOKEN:?export GH_TOKEN first (a token for ${ACCOUNT} with repo scope)}"
command -v gh >/dev/null 2>&1 || { echo "gh is not on PATH" >&2; exit 1; }

echo "==> Checking the token"
ACTUAL="$(gh api user --jq .login)"
[[ "$ACTUAL" == "$ACCOUNT" ]] || { echo "token belongs to '$ACTUAL', expected '$ACCOUNT'" >&2; exit 1; }
echo "    authenticated as $ACTUAL"

echo "==> Checking the repository name is free"
if gh api "repos/$ACCOUNT/$REPO_NAME" >/dev/null 2>&1; then
  echo "repos/$ACCOUNT/$REPO_NAME already exists. Refusing to touch it." >&2
  exit 1
fi
echo "    $ACCOUNT/$REPO_NAME is free"

echo "==> Running the leak scan"
# Any hit here is a stop-the-line event: the tree is about to become public.
if ! "$REPO_DIR/tools/leak_scan.sh" "$REPO_DIR"; then
  echo "leak scan failed; not publishing" >&2
  exit 1
fi

echo "==> Creating the repo"
cd "$REPO_DIR"
git init -q -b main
git add -A
git -c user.name="$AUTHOR_NAME" -c user.email="$AUTHOR_EMAIL" \
    commit -q -m "NCE: grammar, runtime, examples, and project page

Public release accompanying the paper
\"Editing as Language: Teaching LLM Agents a Grammar for Native Context Editing\"."

gh repo create "$ACCOUNT/$REPO_NAME" \
    --public \
    --description "Native Context Editing: a grammar of special tokens that lets LLM agents edit their own context as they generate" \
    --homepage "https://$ACCOUNT.github.io/$REPO_NAME/" \
    --source . --push

echo "==> Enabling GitHub Pages on docs/"
gh api -X POST "repos/$ACCOUNT/$REPO_NAME/pages" \
    -f "source[branch]=main" -f "source[path]=/docs" >/dev/null

echo
echo "Done."
echo "  repo : https://github.com/$ACCOUNT/$REPO_NAME"
echo "  page : https://$ACCOUNT.github.io/$REPO_NAME/"
echo "  Pages takes a minute or two to deploy; check with:"
echo "    gh api repos/$ACCOUNT/$REPO_NAME/pages/builds/latest --jq .status"
