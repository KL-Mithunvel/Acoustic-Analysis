# Explanations

The text behind every "?" panel in the app. One entry per block, headed
`## key: Title`. Edit freely - it is loaded at runtime, no code change needed.

## waveform: Waveform
The sound pressure captured by the microphone, plotted against time. The sharp
jump is the strike; what follows is the part ringing and dying away. A sound
part rings for longer and smoother; a cracked one cuts off quickly. The shaded
band marks the analysis window (the ring), the region every frequency metric is
measured on.

## spectrum: Frequency spectrum (FFT)
How the ring's energy is spread across frequency. Tall narrow spikes are the
part's resonant modes - the notes it "sings". A crack lowers the main mode,
widens the spikes, and drains the high end, so the whole shape shifts left and
flattens. Computed with a Hann window so the spikes are clean.

## octave: Third-octave band levels
The same spectrum grouped into standard 1/3-octave bands (about 30 bars from
25 Hz to 20 kHz), the way acousticians and noise standards describe sound. Each
bar is one band's level. Shown as a shape (levels relative to the total) so it
does not move when you strike harder or change mic gain - only the *distribution*
matters. A dull part has less in the high bars.

## edc: Energy-decay curve
Starting from the strike, how fast the ring's remaining energy falls away, in
decibels (Schroeder backward integration - the standard reverberation-time
method, and steadier than the raw envelope). A straight steep line means fast
damping; a shallow line means the part rings on. **T20 / T30** are this slope
extrapolated to a full 60 dB decay.

## feature_table: Feature values
Every number extracted from this clip. **dominant frequency** - the main ring
mode. **T20 / T30** - reverberation time (longer = rings more). **decay rate** -
dB lost per second (more negative = damps faster). **spectral centroid** -
"brightness" (lower = duller). **high/low ratio** - how much high-frequency
energy there is relative to low. **SNR** - ring level over the background before
the strike; below the configured minimum the clip is marked RETEST.

## grade: Grade
A first-pass, rule-based verdict against the reference profile of known-good
parts: GOOD, BORDERLINE, DEFECTIVE, or RETEST (clip not usable - retry). The
reasons list says exactly which features drove it. This is not a trained model;
it is a transparent starting point, and every threshold is in `config.yaml`.

## filter_response: Filter frequency response
The gain the current filter chain applies at each frequency, in dB. 0 dB means
"passes through untouched"; negative means "attenuated". The band-pass rolls off
the ends, each notch carves a narrow dip, and a weighting curve tilts the whole
thing. This is exactly what is applied to the signal before analysis - what you
see here is what you get.

## noise_profile: Noise profile
A recording of the background with nothing being tested - the room, the
conveyor, the fans. Its spectrum and level become the reference the denoiser
subtracts, and its level sets how strong a ring has to be before a measurement
is trustworthy.

## nc_rating: Noise Criterion (NC) rating
A single number summarising how loud a room's background is, by comparing its
octave-band levels to a standard family of curves. Lower is quieter. Used to
qualify the test environment, not to grade a part.

## denoise: Denoise preview
Stationary background noise estimated from the noise profile and subtracted from
the clip, band by band, in the time-frequency domain. Useful to *hear* and *see*
a cleaner ring. Treat features taken from denoised audio with care - the process
can smear or invent detail; that is why it is off in the analysis path unless
you turn it on.

## level_meter: Input level
The live microphone level. Aim for the loudest part of a strike to sit well
below the top with headroom to spare - if it pins the top, the recording is
clipped and useless. If it never moves, check the device and the input gain.

## spectrogram: Spectrogram
Frequency (vertical) against time (horizontal), with colour as level. A live
scrolling view of what the microphone hears - steady horizontal lines are
constant tones (mains hum, motor whine); broadband vertical smears are taps,
knocks and clicks.
