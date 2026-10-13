# Reproduce the recorded demo

[Actual 75.4-second browser recording](assets/tracefi-demo.webm) ·
[GIF excerpt](assets/demo.gif) ·
[Investigation screenshot](assets/dashboard-investigation.png) ·
[Counterfactual screenshot](assets/dashboard-counterfactual.png).

The video renders **stdout from real local CLI commands**, then navigates the real
packaged dashboard in Chromium. It is not a recording of a native terminal window.
All states, proposals and outcomes are explicitly synthetic. There is no audio,
real capital, historical feed or fabricated screenshot.

## Manual 60–90 second storyboard

1. **0–9 s:** `tracefi demo --case-study`: portfolio, proposal and provenance.
2. **9–18 s:** `tracefi show latest`: actual recorded context and configurations.
3. **18–27 s:** `tracefi analyze latest`: likely retrieval issue; distinguish loss
   from evidence supporting the omission.
4. **27–36 s:** run the single-trend counterfactual below; compare Protocol B 25k
   with Protocol A 20k, without a hypothetical return.
5. **36–45 s:** `tracefi serve`; open the local dashboard and choose the trace.
6. **45–54 s:** inspect timeline/evidence and the failure attribution tab.
7. **54–63 s:** counterfactual tab; choose `lending-v1`, restore B's −0.41 trend.
8. **63–75 s:** compare `lending-v1`/`lending-v2`: lower proposed costs coexist with
   more policy rejections and larger proposed concentration.

```bash
tracefi demo --case-study
tracefi show latest
tracefi analyze latest
tracefi counterfactual latest --adapter lending-v1 \
  --feature context.markets.protocol_b.liquidity_trend_24h --value -0.41
tracefi eval --baseline lending-v1 --candidate lending-v2 --dataset lending
tracefi serve
```

## Automated capture and browser verification

```bash
python -m pip install -e '.[ui]'
python -m playwright install chromium
python scripts/check_dashboard.py --assets /tmp/tracefi-demo-new --record-video
```

Use a fresh output directory; existing media is refused. The script uses a temporary
DB and dynamically selected local port, tests empty/list/detail/filter/evidence/
XSS/redaction/counterfactual behavior, records actual command output and UI actions,
and shuts down its server. The default without `--record-video` runs quickly.

To generate the checked-in GIF excerpt from a new recording, with free FFmpeg:

```bash
ffmpeg -i /tmp/tracefi-demo-new/tracefi-demo.webm -ss 45 -t 18 \
  -filter_complex '[0:v]fps=5,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse' \
  /tmp/tracefi-demo-new/demo.gif
```

UUIDs, timestamps, durations and viewport rendering vary. The synthetic decisions,
metrics and assertions are reproducible. Optional screen recording software can
capture the manual storyboard with voiceover; no additional recording is claimed.
