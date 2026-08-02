#!/bin/bash
set -e

echo "🚀 Bootstrapping kiachahye.pk system..."

# 1. Backend setup
echo "📦 Setting up backend..."
cd backend
python -m venv .venv
source .venv/bin/activate || source .venv/Scripts/activate
pip install -e ".[dev]"
playwright install chromium --with-deps
cp .env.example .env
cd ..

# 2. Frontend setup
echo "📦 Setting up frontend..."
cd frontend
npm install
cp .env.local.example .env.local
cd ..

# 3. Supabase setup (if CLI is available)
if command -v supabase &> /dev/null
then
    echo "🗄️ Initializing Supabase..."
    supabase start
else
    echo "⚠️ Supabase CLI not found. Skipping local DB start."
fi

echo "✅ Bootstrap complete!"
