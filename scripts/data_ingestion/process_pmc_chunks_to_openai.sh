#!/usr/bin/env bash
for f in pmc_chunks/*.json; 
do 
    echo $f; 
    outfile=${f/pmc_chunks/pmc_chunks_embedding}; 
    if [ -e $outfile ]
    then
        echo "skipping $outfile"
        continue
    fi
    python embed_chunks.py --input $f --output $outfile --yes
done
