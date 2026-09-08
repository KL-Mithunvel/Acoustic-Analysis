"""Acoustic-Analysis - impact-acoustic analysis and data-labelling workbench.

Package layout:
  config.py     load config.yaml
  dsp/          pure signal processing - numpy array in, numbers out, no I/O
  features.py   orchestrates dsp/* into one feature dict per clip
  classify/     reference profile + rule-based grading
  io/           microphone / WAV / SQLite - the only modules that touch the outside
  app/          Tkinter GUI (thin)
"""

__version__ = "0.1.0"
