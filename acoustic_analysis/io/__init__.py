"""Input / output - the only modules that touch the microphone, the speakers,
the filesystem or the database. Everything here is a thin wrapper; the logic it
feeds lives in ``dsp`` and ``features`` (Development Rule 1).
"""
