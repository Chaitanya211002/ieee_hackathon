# WIN node test results

- Node: `http://192.168.0.113:8001`
- Speech model: large-v3-turbo on cuda (float16)
- Sound model: MIT/ast-finetuned-audioset-10-10-0.4593 on cpu
- GPU: NVIDIA GeForce RTX 3060 Laptop GPU (6144 MB)
- Offline mode: True

| Test | Input | Result | Speed | Status |
|---|---|---|---|---|
| Speech to text | bench_note_tts.wav | WER 0.0%, language en | 0.87s for 10.38s of audio, cuda | PASS |
| Speech to text (lab hint) | bench_note_tts.wav | WER 0.0%, language en | 0.69s for 10.38s of audio, cuda | PASS |
| Sound identification | timer_beeps.wav | top 3: Dial tone 0.542, Busy signal 0.399, Beep, bleep 0.043 | 1.39s, cpu | PASS |
| Sound identification | Alarm01.wav | top 3: Ringtone 0.871, Music 0.566, Telephone bell ringing 0.1 | 1.33s, cpu | PASS |
| No speech means no text | silence.wav | text: "" | 0.3s | PASS |
| Speech + timer in one clip | note_with_timer.wav | WER 0.0%; events: speech, alarm_or_timer | - | PASS |
| Phone voice memo (m4a, AAC) | note.m4a | WER 0.0% | 0.72s | PASS |
| Browser recording (webm, Opus) | note.webm | WER 0.0% | 0.67s | PASS |
| Video clip (mp4, H.264 + AAC) | clip.mp4 | WER 0.0% | 0.7s | PASS |
| Rejects non-audio files | not_audio.txt | HTTP 415 | - | PASS |
| Code runs, stdout captured | print(6 * 7) | stdout: 42 | 0.1s | PASS |
| Uploaded CSV to plot | plate.csv | slope=0.193; standard_curve.png 18720 bytes | 5.21s | PASS |
| Errors come back as a traceback | x = 1 / 0 | exit_code 1 | 0.11s | PASS |
| No network inside the sandbox | urlopen(example.com) | exit_code 1 | 0.2s | PASS |
| Runaway code is stopped | while True: pass | exit_code -1; Timed out after 20 s | 20.33s | PASS |
| Rejects unsafe file names | ../escape.txt | HTTP 400 | - | PASS |

Speech clips are synthetic (Windows text-to-speech); the sound clips are generated tones or Windows system sounds. These are smoke tests, not accuracy figures.
