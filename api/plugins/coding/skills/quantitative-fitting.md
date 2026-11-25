---
name: quantitative-fitting
title: Quantitative Data and Peak Fitting
description: Check units and axis semantics, fit peaks with a baseline window, preserve numeric precision.
kinds: dev,auto,coding
triggers: 拟合,fit,spectrum,光谱,peak,峰,raman,拉曼,wavelength,波长,axis,坐标轴,单位,precision,精度,signal,信号,curve,曲线,baseline,基线,offset
version: 1.0.0
---

## Read the requirement as a contract
Extract the exact output path, keys, units and precision. If precision is not stated, write at least 6 significant digits and never round to 2 decimal places by habit.

## Establish the coordinate before fitting
Read the data header and sample values. Decide what the x axis actually is: raw wavelength, reciprocal wavelength, wavenumber, log scale, encoded category, etc. Convert to the coordinate the task names. When the domain has known landmarks (e.g. graphene G ~1580 cm-1 and 2D ~2670 cm-1), use them as a sanity check, not as hard-coded answers.

## Fit peak plus background together
1. Choose a window that includes the baseline on both sides, roughly 10-20x the peak half-width.
2. Fit the background (constant, linear or quadratic) and the peak together.
3. Report the background evaluated at the peak center as `offset`.
4. Try at most two peak models (Lorentzian / pseudo-Voigt). Pick by residual RMS or BIC, then commit.

## Verify independently before writing
- Check the fitted center against the data maximum and known landmarks.
- Check the half-max crossings (FWHM ~ 2*gamma for a Lorentzian).
- Check the peak area against pi*amplitude*gamma for a Lorentzian.
- If a checker or test exists, run it. Otherwise validate the output schema and every numeric field.

## Stop condition
After the two allowed variants and one independent check, write the final file and stop. Do not keep re-fitting or re-scanning the same spectrum.
