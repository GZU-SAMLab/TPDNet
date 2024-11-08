#!/bin/bash
#SBATCH --job-name=zhangtianhan_test
#SBATCH --output=%j.out
#SBATCH --error=%j.err
python train1.py  --experiment_name="monodrt_mycode-25"
