"""Tkinter desktop GUI (laptop, mouse + keyboard).

Plain ``ttk.Notebook`` tabs first; an instrument-look restyle (dark theme, fixed
button rail, soft-key bar) comes as a later pass over the same screens - see
``docs/UI_DESIGN.md``. Widgets live on the Tk main thread; recording and analysis
run on a background worker and return through a queue.
"""
