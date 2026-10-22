# REVIVE in GitHub Codespaces

The app installs itself (about 5 minutes the first time) and starts on port 8000.

1. Open the **Ports** tab at the bottom of this window. Port **8000 (REVIVE app)** shows a link.
2. Click the globe icon next to it to open REVIVE in a new browser tab.
3. To let other people open it, right-click port 8000, choose **Port Visibility**, then **Public**
   (the start script tries to do this for you). Copy the link and share it.

The link works only while this codespace is running. It stops after 30 minutes without use
(change that under github.com/settings/codespaces, up to 4 hours); start it again from the
repository page (**Code**, **Codespaces**) and the same link comes back.
Free accounts get 60 hours a month. Stop the codespace when you are done:
github.com/codespaces, then **...**, **Stop codespace**.

If the page does not load, the app may still be starting: wait a minute, or run
`bash .devcontainer/start.sh` in the terminal and look at `/tmp/revive.log`.
