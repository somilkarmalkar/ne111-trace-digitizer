# Verification record

Verified November 17, 2026 (America/Toronto).

- Live app: https://ne111-trace-somil.streamlit.app/
- Repository: https://github.com/somilkarmalkar/ne111-trace-digitizer
- Application source commit: `9034b9b0b4c16e6aa9456a8bb841161f64f5ccc4`
- `app.py` SHA-256: `d82c1af5b94a8a7a83965f51f7309c33194d5e38b962a2b58ca2930fb417b1ee`
- Tested environment: Python 3.14, Streamlit 1.67.0, pandas 2.3.3, Pillow 12.1.1.

## Automated checks

`python -m pytest tests -q` completed with **22 passed**, plus **14 passed subtests**.

Coverage includes rotated and skewed affine calibration, reversed axes, linear/semi-log/log-log mappings, inverse coordinates, degenerate references, invalid logarithmic values, overflow, two-row CSV headers, Unicode/quoted names, unequal dataset lengths, all four image formats, grayscale/high-bit-depth conversion, EXIF orientation, transparency, GIF/TIFF frames, dataset creation/rename/deletion/undo/redo, recalibration guards, image replacement, table edits/additions/deletions, and JSON workspace restoration.

## Browser and deployment checks

- Opened the deployed Community Cloud app and used its canvas.
- Clicked the same point near (5, 4.8) at fitted and 100% zoom. Results were approximately (5.0211, 4.8035) and (5.0110, 4.8042), consistent with subpixel manual placement.
- Edited the first table row's x value to 6 and observed its marker move horizontally to x = 6.
- Downloaded the actual CSV and parsed it independently. Confirmed the dataset header, x/y header, three rows, and the edited x = 6 value.
- Confirmed the app's **Make this app public** control is enabled.
- Requested the app, its embedded page and health endpoint without browser login cookies: all returned HTTP 200; health returned `ok`, with no authentication redirect.
- Saved a screenshot of the verified hosted interface alongside the project archive.

## Requirements coverage

| Rubric category | Implemented behavior |
| --- | --- |
| Ease of use (25) | Guided O/X/Y reference picks, instructions, examples, automatic next step, undo/redo and validation |
| Appearance/readability (20) | Clear controls, labeled canvas, consistent colors, point numbers, legend, precision magnifier and narrow-screen layout |
| Calibration/digitizing (15) | Original-pixel coordinates; rotated/skewed affine basis; independent linear or logarithmic axes; numeric reference adjustment |
| Datasets/editing (15) | Multiple named datasets, distinct colors, switching, deletion, reversible edits and inverse-mapped table changes |
| Axis labels/CSV (15) | Editable labels, all datasets in paired columns, required two header rows, blank padding and full float precision |
| Image upload (10) | PNG/JPEG/GIF/TIFF, color/grayscale, EXIF orientation and selectable frames/pages |
| Optional bonus features | Cursor-centered zoom/pan, plus a live editable table whose changes move markers |

This records implementation and observed checks, not an awarded or guaranteed grade. Three-point affine calibration does not correct photographic perspective or lens distortion. Save a JSON workspace before leaving a session. Community Cloud availability and any later source changes should be checked again before submission.

## Submission remaining

Upload `app.py` to LEARN and paste the live Streamlit URL in the submission comment. The assignment has not been submitted to LEARN by this assistant.
