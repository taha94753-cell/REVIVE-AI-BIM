# Running REVIVE with Claude Code: step by step, in plain words

Claude Code is a helper that works inside your project folder. You type what you want in normal English; it runs the commands and edits the files for you. It asks before running anything.

## Part A: one-time installation (about 20 minutes)

**1. Install Python 3.12**
- Download it from python.org. In the installer, tick **"Add python.exe to PATH"** before clicking Install.

**2. Install Git for Windows (recommended)**
- Download it from git-scm.com and click Next through the installer. Claude Code works best with it.

**3. Install Claude Code**
1. Press the Windows key, type **PowerShell**, and open it.
2. Paste this line and press Enter:
   ```
   irm https://claude.ai/install.ps1 | iex
   ```
3. Close PowerShell and open it again.
4. Type `claude --version`. If it prints a version number, it is installed.

You need a paid Claude plan (Pro or Max) or an Anthropic Console account; the free plan does not include Claude Code. Official instructions: https://code.claude.com/docs/en/setup

**4. Put the project somewhere simple**
- Unzip `revive-aibim.zip` to `C:\Projects\revive-aibim`. Avoid long paths and OneDrive folders.

## Part B: first launch with Claude Code (about 10 minutes)

1. Open PowerShell and go to the project:
   ```
   cd C:\Projects\revive-aibim
   ```
2. Start Claude Code:
   ```
   claude
   ```
3. The first time, a browser opens. Log in with your Claude account and come back to PowerShell.
4. If it asks whether you trust this folder, choose **Yes**.
5. Claude Code reads `CLAUDE.md` by itself, so it already knows what the project is.
6. Type this and press Enter:
   ```
   Set up this project: create a virtual environment, install requirements-dev.txt, run "python -m revive setup", then run the tests.
   ```
7. It shows each command before running it. Read it and approve. At the end it should say **21 passed**.

## Part C: launching the app

Use a **separate window** for the app, so Claude Code stays free for changes.

1. Double-click `run.bat` in the project folder. The first time, run `setup.bat` instead if you skipped Part B.
2. A black window opens and stays open. That is the server; leave it running.
3. Your browser opens **http://localhost:8000**. If it does not, type that address yourself.
4. To stop the app, click the black window and press **Ctrl + C**.

You can also ask Claude Code: "Start the app on port 8000". It will run the server, but that Claude Code window is then busy until you stop it.

## Part D: using the live phone link

1. Connect the phone and the laptop to the **same Wi-Fi**, or the laptop to the phone's hotspot.
2. In the app: run a forecast on Assess, then press **Start monitoring this project** on Live.
3. Scan the QR code with the phone.
4. If the phone cannot open it, Windows Firewall is blocking it. When Windows asks, allow Python on **private networks**, or ask Claude Code: "Help me allow port 8000 through Windows Firewall on private networks."

## Part E: everyday jobs to ask Claude Code

Type these inside Claude Code, one at a time:

| You want to | Type |
|---|---|
| Use your P6 schedule | "Import data/raw/my_project.xer as the baseline schedule and tell me what the import report says." |
| Add new survey data as a test | `/evaluate-new-data data/raw/new_projects.xlsx` |
| Retrain after adding data | `/retrain` |
| Run without BIM by default | "Set the app to start with no BIM model connected." |
| Change the weather rules | "Change the lost-day rain threshold to 15 mm and explain the effect." |
| Fix an error | Paste the error message and type "fix this". |
| Understand something for the viva | "Explain how the recovery LP works as if I am in my defence." |

## Part F: good habits

- **Commit before big changes.** Ask "commit everything with the message 'before P6 import'". Then you can always go back.
- **Read before approving.** Claude Code shows each command; approve only what you understand.
- **Run the tests after each change.** "Run the tests."
- **Never upload `data/raw/` anywhere.** It contains the private project key. Claude Code knows this rule from `CLAUDE.md`.
