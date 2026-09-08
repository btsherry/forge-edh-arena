# Making your own W.O.P.R.-register voice (ElevenLabs)

The packaged stock lines were rendered from the project owner's own voice
clone. ElevenLabs does not let a cloned or designed voice be shared to other
accounts, and a Professional Voice Clone of the film's actor is neither
possible nor permitted. So live lines under your own key need a voice you
own. Either of these works; the runner finds a voice named exactly
`Jousha-W.O.P.R.` in your library by itself, or set `ARENA_VOICE_ID`.

## Voice Design prompt (takes about a minute)

In ElevenLabs → Voices → Add → Voice Design, paste:

> A flat, deliberate, slightly synthetic male computer voice from a 1980s
> military mainframe. Even pitch, narrow range, over-enunciated consonants,
> no emotion, no breathiness, a calm measured pace with small pauses between
> phrases. Mid-low register, dry, close-miked, as if heard through a small
> loudspeaker.

Preview with: "Greetings, Professor Falken. Shall we play a game?" Pick the
candidate with the flattest delivery. Name it `Jousha-W.O.P.R.`.

## Settings the runner sends with every line

| setting | value |
|---|---|
| model | `eleven_flash_v2_5` |
| stability | 0.90 |
| similarity_boost | 0.80 |
| style | 0.0 |
| use_speaker_boost | true |
| speed | 0.92 |
| output_format | `pcm_24000` (Creator tier and above; MP3 fallback is automatic) |

The film-match processing (loudspeaker EQ, 50 Hz tremolo, slap echo,
compression, digital hitches) is applied after rendering, by `ffmpeg` when it
is installed or by the built-in pure-Python chain when it is not — so the
designed voice itself should be clean and flat, not pre-processed.
