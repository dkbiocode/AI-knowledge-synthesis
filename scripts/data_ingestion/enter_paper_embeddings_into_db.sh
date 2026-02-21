#!/usr/bin/env bash

for f in pmc_chunks/*.json
do
    fname=$(basename $f)
    cmd="python load_paper_chunks.py --file pmc_chunks/$fname --embedding pmc_chunks_embedding/$fname"
    eval $cmd
done
