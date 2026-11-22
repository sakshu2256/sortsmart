#!/bin/bash
# Script to push SortSmartV2 to https://github.com/sakshu2256/sortsmart.git

TOKEN="$1"

if [ -z "$TOKEN" ]; then
    echo "Usage: ./push_to_github.sh <YOUR_GITHUB_PERSONAL_ACCESS_TOKEN>"
    echo ""
    echo "To get your token:"
    echo "1. Go to https://github.com/settings/tokens/new"
    echo "2. Check the 'repo' box"
    echo "3. Generate and copy the token (starts with ghp_...)"
    echo "4. Run: ./push_to_github.sh ghp_your_token_here"
    exit 1
fi

cd "$(dirname "$0")"

echo "Setting remote URL with authentication..."
git remote set-url origin "https://sakshu2256:${TOKEN}@github.com/sakshu2256/sortsmart.git"

echo "Pushing code to https://github.com/sakshu2256/sortsmart.git..."
git push -u origin main --force

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ SUCCESS! All SortSmart code has been uploaded to https://github.com/sakshu2256/sortsmart"
    # Remove token from remote URL for security
    git remote set-url origin "https://github.com/sakshu2256/sortsmart.git"
else
    echo "❌ Push failed. Please verify that your token has 'repo' permissions."
fi
