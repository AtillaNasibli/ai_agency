#!/usr/bin/env bash
# Re-hire the 8 AI Employees with the official installer (needs Node >= 18 and internet).
set -euo pipefail
ROLES=(gtm-engineer seo-employee web-dev-employee social-media-employee \
       ad-manager-employee sales-employee customer-satisfaction-employee chief-of-staff)
mkdir -p employees
for r in "${ROLES[@]}"; do
  echo ">>> Hiring $r"
  npx ai-employees hire "$r" --to "employees/$r"
done
