# Deployment

## Local (recommended for the defence)
Run `setup.bat` then `run.bat` (or `./setup.sh`, `./run.sh`).

The frontend has no CDN dependencies: Three.js and the fonts are vendored. The app runs with Wi-Fi off. Test that before the defence.

## Docker
```bash
docker compose up --build        # http://localhost:8000
```
`data/` and `bim/` are mounted as volumes, so saved assessments and uploaded models survive restarts. The Dockerfile has not been built in the environment where this repository was created. Run it once and fix anything platform-specific.

## Hugging Face Spaces (free public link)
1. Create a Space with SDK "Docker".
2. Push this repository.
3. Add this header at the very top of README.md:
   ```
   ---
   title: REVIVE
   sdk: docker
   app_port: 8000
   ---
   ```
4. Make sure `data/raw/` is not pushed (it is git-ignored). Confirm permission for `data/processed/`.

## Render / Railway
Use the Dockerfile. Set `PORT` if the platform assigns one; the start command already reads it. Free tiers sleep, so wake the app a few minutes before a demo.
