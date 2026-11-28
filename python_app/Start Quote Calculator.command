#!/bin/bash
# Double-click this file in Finder to start the Quote Calculator.
# The first time, it sets up a private copy of the Python libraries in a folder called .venv
# (this needs internet and takes a minute). After that it starts in a few seconds.
# Keep the Terminal window that opens; closing it stops the app.

cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is not installed. Install it from https://www.python.org/downloads/ (see GUIDE.md, step 1)."
  read -r -p "Press Enter to close this window."
  exit 1
fi

if [ ! -x .venv/bin/python3 ]; then
  echo "Setting up for the first time..."
  python3 -m venv .venv || { read -r -p "Could not set up. Press Enter to close."; exit 1; }
fi

# Install the libraries again only when requirements.txt has changed.
if ! cmp -s requirements.txt .venv/installed-requirements.txt; then
  echo "Installing the libraries the app needs..."
  .venv/bin/python3 -m pip install --quiet --upgrade pip
  if .venv/bin/python3 -m pip install --quiet -r requirements.txt; then
    cp requirements.txt .venv/installed-requirements.txt
  else
    echo "Could not install the libraries. Check the internet connection and try again."
    read -r -p "Press Enter to close this window."
    exit 1
  fi
fi

.venv/bin/python3 app.py
