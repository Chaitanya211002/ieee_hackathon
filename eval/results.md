# BenchLog eval: practice pack

Run 2026-11-19T15:45-05:00 · 100 items · 24 min total · all inference local

Models: vision/text `qwen3-vl:8b-instruct`, coder `qwen2.5-coder:7b`, embeddings `nomic-embed-text`, speech Whisper large-v3-turbo, sounds AST AudioSet. Video: 10 frames, mode `sheets`.

| Modality | Metric | Result |
|---|---|---|
| Image | Counting accuracy | 93% (14/15) |
| Image | Identification accuracy (lenient) | 100% (10/10) |
| Audio | Mean WER, transcription items | 2.1% (5 clips) |
| Audio | Speech Q&A accuracy (lenient) | 80% (4/5) |
| Audio | Sound identification accuracy (answer) | 80% (8/10) |
| Audio | Sound in AST top-3 labels | 90% (9/10) |
| Text | Accuracy, answerable (lenient) | 93% (14/15) |
| Text | Correct refusal, unanswerable | 100% (5/5) |
| Text | False refusal, answerable | 0% (0/15) |
| Code | Hidden unit tests passed | 90% (18/20) |
| Code | Generated code ran without error | 100% (20/20) |
| Video | Question accuracy | 67% (10/15) |

## Latency

| Modality | Node | Items | Mean (s) | Max (s) |
|---|---|---|---|---|
| audio | M5 | 20 | 5.4 | 15.3 |
| code | M5 | 20 | 22.9 | 44.0 |
| image | M5 | 25 | 9.6 | 13.3 |
| text | M5 | 20 | 7.0 | 12.3 |
| video | M5 | 15 | 34.6 | 39.9 |

## Per item (pass/fail only; answers stay out of the repo per the pack license)

| Modality | Pass | Fail |
|---|---|---|
| image | p_img_001, p_img_002, p_img_003, p_img_004, p_img_005, p_img_006, p_img_007, p_img_008, p_img_009, p_img_010, p_img_011, p_img_012, p_img_014, p_img_015, p_img_016, p_img_017, p_img_018, p_img_019, p_img_020, p_img_021, p_img_022, p_img_023, p_img_024, p_img_025 | p_img_013 |
| audio | p_aud_001, p_aud_002, p_aud_003, p_aud_004, p_aud_005, p_aud_006, p_aud_008, p_aud_009, p_aud_010, p_aud_011, p_aud_012, p_aud_014, p_aud_015, p_aud_016, p_aud_017, p_aud_018, p_aud_020 | p_aud_007, p_aud_013, p_aud_019 |
| text | p_txt_001, p_txt_002, p_txt_003, p_txt_004, p_txt_006, p_txt_007, p_txt_008, p_txt_009, p_txt_010, p_txt_011, p_txt_012, p_txt_013, p_txt_014, p_txt_015, p_txt_016, p_txt_017, p_txt_018, p_txt_019, p_txt_020 | p_txt_005 |
| code | p_code_001, p_code_002, p_code_003, p_code_004, p_code_005, p_code_006, p_code_007, p_code_009, p_code_010, p_code_011, p_code_012, p_code_013, p_code_014, p_code_015, p_code_017, p_code_018, p_code_019, p_code_020 | p_code_008, p_code_016 |
| video | p_vid_001, p_vid_002, p_vid_003, p_vid_004, p_vid_005, p_vid_006, p_vid_007, p_vid_010, p_vid_014, p_vid_015 | p_vid_008, p_vid_009, p_vid_011, p_vid_012, p_vid_013 |

Scoring notes: lenient = at least half the reference answer's content words appear in the model's answer. Image counts compare the first number in the VLM answer (a VLM estimate; plates also get an OpenCV count). WER is word error rate against the reference transcript. Code items count as passed only if the pack's unit tests pass on the generated code. Video answers are scored against each clip's generator parameters (count, direction, colour order, words).
