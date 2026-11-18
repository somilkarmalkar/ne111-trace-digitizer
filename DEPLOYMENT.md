# Deploy and submit

Live app: [Trace](https://ne111-trace-somil.streamlit.app/)

Source: [GitHub repository](https://github.com/somilkarmalkar/ne111-trace-digitizer)

The project must run on **Streamlit Community Cloud**. A local address or a source-code repository link is not a substitute for the running app URL. The rubric states that an app that remains inaccessible after a retry receives 0/100.

## Deploy

1. Put `app.py` and `requirements.txt` at the root of a GitHub repository that you own or administer. Keep any provided `.streamlit/config.toml` in its `.streamlit` directory. Do not upload a virtual environment or cache folders.
2. Sign in at [Streamlit Community Cloud](https://share.streamlit.io/) and connect the GitHub account that owns the repository.
3. In the matching workspace, choose **Create app**, then **Yup, I have an app**.
4. Select the repository, the branch containing the final code, and `app.py` as the entrypoint. You can enter a missing repository manually or use **Paste GitHub URL**.
5. Open **Advanced settings** and select **Python 3.14** (the version used for this deployment and local testing). No API keys or secrets are needed by this application.
6. Choose a recognizable available app URL if desired, then deploy. Wait for the build to finish and for the actual app to appear. If it fails, inspect the build logs, correct the issue, and redeploy.
7. Copy the actual running URL ending in `.streamlit.app`.

Official guidance: [deploy an app](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy), [declare dependencies](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies), and [connect GitHub](https://docs.streamlit.io/deploy/streamlit-community-cloud/get-started/connect-your-github-account).

## Verify the public app

Open the running URL in a private/incognito window while signed out. Confirm that a marker can use it without needing your GitHub or Streamlit login. If access is restricted, adjust the app's sharing settings and retest.

Complete this short acceptance check on the deployed version:

- Upload a plot, calibrate its axes, and click at least three known points. Check the resulting numbers.
- Repeat with a rotated scan and a plot with one logarithmic axis.
- Create and rename two datasets. Check their distinct marker colors. Undo a click and delete a dataset.
- Zoom, pan, and click a known location. Check that zoom did not change its numerical coordinates.
- Edit a table value and confirm its marker moves to the corresponding location.
- Download the CSV. Open it as text or in a spreadsheet and verify the dataset row, axis-label row, values, and blank padding for unequal dataset lengths.
- Refresh the public app and confirm it still opens without an exception. Wake it if Community Cloud has put it to sleep, then check again shortly before submission.

## Submit to LEARN

1. Upload the final **`app.py`** file so the marker can inspect the code.
2. Paste the verified, publicly accessible **Streamlit Community Cloud app URL** into the submission comment box.
3. Confirm that the upload and comment are both saved, and open the submitted link once more.

Deploy the same final version that you submit. Keep the app and its GitHub source available throughout marking. Do not claim a deployment URL before it has actually launched and passed the public-access check.
