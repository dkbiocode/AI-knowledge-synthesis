#!/usr/bin/env bash

# activate conda environment
source /Users/david/miniconda3/etc/profile.d/conda.sh
conda activate openai

streamlit run scripts/query/streamlit_aspect_search.py
