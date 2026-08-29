# Bundled UI fonts

Drop the `.ttf` files here. The app registers them for its own process with
`AddFontResourceEx(..., FR_PRIVATE)`, so nothing is installed system-wide, and
falls back to Segoe UI and Consolas when this directory is empty.

| Family | Used for | Licence | Source |
| --- | --- | --- | --- |
| Be Vietnam Pro | All UI text | OFL 1.1 | https://fonts.google.com/specimen/Be+Vietnam+Pro |
| JetBrains Mono | File list rows | OFL 1.1 | https://fonts.google.com/specimen/JetBrains+Mono |
| Liberation Serif | Text drawn into translated PDFs | OFL 1.1 | https://github.com/liberationfonts/liberation-fonts |

Liberation Serif is the output font for every supported target language, which
are all Latin-script. It is committed rather than downloaded at build time
because the engine needs it whether it runs from the packaged app or from a
source checkout, and because the output must not change depending on which
machine produced it - the previous code read `C:/Windows/Fonts/times.ttf`, so a
document came out in Times on one machine and in a sans-serif on another.

Its metrics match Times New Roman, so switching from the old Windows path does
not reflow anything. To use a different serif, drop it in here, point
`LATIN_SERIF_NAME` in `pdf2zh/high_level.py` at it, and keep its licence file
next to it. It needs the Vietnamese precomposed range (U+1EA0-U+1EF9); a serif
without those renders the diacritics as empty boxes. The italic and bold weights
are here for the style work that is not wired up yet - only Regular is used
today.

Regular and Bold weights are enough. Be Vietnam Pro is drawn for Vietnamese
diacritics, which stack tall and collide in fonts that were not designed for them.

Both are OFL, so redistributing them inside the packaged app is fine. Keep the
`OFL.txt` that ships with each family next to the fonts.
