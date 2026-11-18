# Trace | Plot Digitizer

A single-page Streamlit app for extracting numerical data from an image of a graph. The complete application is in `app.py`; the browser canvas is embedded in that file.

## Run locally

Use Python 3.12 or another Python version supported by the pinned dependencies.

```text
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

On macOS or Linux, activate the environment with `source .venv/bin/activate`.

## Digitize a plot

1. Upload a PNG, JPG/JPEG, GIF, or TIFF image. Color and grayscale images are supported.
2. Enter meaningful x and y axis labels, including units when available. Select linear or logarithmic scaling separately for each axis.
3. Calibrate with three clicks: a shared reference **O**, a second point **X** along the x axis, and a second point **Y** along the y axis. Enter the corresponding x and y values. For a logarithmic axis, every reference value must be greater than zero. **O** means the shared reference point; it need not be numerical zero.
4. Select or create a named dataset and click its data points. Each dataset uses its own color. Zoom in for precise placement; pan to move around the enlarged image.
5. Review the values in the live table. Edit a coordinate to move its marker on the image. Undo an accidental click, or delete a dataset that is no longer needed.
6. Download the CSV and check its header names and numerical values before using it elsewhere.

Calibration handles scan rotation directly. Choose well-separated reference points on the intended axis directions. Three points on or almost on one straight line cannot define two independent axes.

## CSV layout

The export has two columns per dataset, with a dataset-name row followed by an axis-label row. Shorter datasets are padded with empty fields.

```csv
Series A,,Series B,
Time (s),Distance (m),Time (s),Distance (m)
1,10,1,80
3,30,3,60
5,50,,
```

Dataset names and axis labels are quoted automatically when needed. Values follow click order. For logarithmic plots, exported values are the original physical values, not their logarithms.

## Deployment and submission

See `DEPLOYMENT.md` for Streamlit Community Cloud deployment and the final submission checks. Upload `app.py` to LEARN and include the verified public `streamlit.app` URL in the submission comment, as required by the assignment.

## How calibration works

The image vectors from **O** to **X** and from **O** to **Y** form a two-dimensional coordinate basis. A 2-by-2 inverse maps image pixels into fractional axis positions, so a rotated scan does not need to be physically straightened. Those fractions interpolate the entered reference values. A logarithmic axis interpolates their base-10 logarithms and then exponentiates the result. The inverse mapping places edited table values back on the image.

Manual clicking introduces uncertainty. Zooming and using reference ticks far apart reduce placement error. Perspective-distorted photographs and curved axes are outside the three-point affine model.
