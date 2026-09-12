# Fonts

Gujarati subtitles need a Gujarati-capable font, or they render as empty boxes.

**Download Noto Sans Gujarati** (free, SIL Open Font License) and drop the
`.ttf` here:

- https://fonts.google.com/noto/specimen/Noto+Sans+Gujarati

Place the file at:

    assets/fonts/NotoSansGujarati-Bold.ttf

(matching `subtitles.font_file` in `config.yaml`). The subtitle burner also
passes this folder to ffmpeg via `fontsdir`, so any Gujarati `.ttf` here works —
just set the internal font family name in `config.yaml` if you use a different one.
