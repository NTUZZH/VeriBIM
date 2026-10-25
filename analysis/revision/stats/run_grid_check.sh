#!/bin/bash
# quadrature grid accuracy check, pinned to cores 16-23
cd "$(dirname "$0")"
exec taskset -c 16-23 env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 \
  python grid_check.py
