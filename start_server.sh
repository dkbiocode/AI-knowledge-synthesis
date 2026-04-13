#!/usr/bin/env bash
set -e

# Activate conda environment
source /Users/david/miniconda3/etc/profile.d/conda.sh
conda activate openai

# Check if Supabase is running, start if needed
echo "Checking Supabase status..."
if ! supabase status &>/dev/null; then
    echo "Supabase not running. Starting Supabase..."
    supabase start
else
    echo "Supabase is already running."
fi

# Start Streamlit app
echo "Starting Streamlit app..."
streamlit run scripts/query/streamlit_aspect_search.py
