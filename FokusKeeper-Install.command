#!/bin/bash
# FokusKeeper -- one-click installer.
# Double-click this file in Finder to install or update FokusKeeper.
# It downloads one reviewed release revision to ~/FokusKeeper, then runs
# that copy's own install.sh. It never follows the mutable default branch.

echo ""
echo "FokusKeeper Installer"
echo "======================"
echo ""

REPO_URL="https://github.com/cipshadow/fokuskeeper.git"
# This is the commit reviewed for the release containing this installer. A
# future release ships a new installer with a new immutable commit value.
RELEASE_COMMIT="6c5f36eb00b22dcdfc9cc5b2aabd917ac16eb884"
INSTALL_DIR="$HOME/FokusKeeper"

# git ships as an Xcode Command Line Tools stub on a fresh Mac. The first
# time anything tries to run it with no CLT installed, macOS offers to
# install them -- accept that if it appears, then double-click this file
# again once it finishes (a few minutes).
if ! command -v git > /dev/null 2>&1; then
    echo "git isn't available yet. If macOS just offered to install the"
    echo "Command Line Tools, accept that, wait for it to finish, then"
    echo "double-click this file again."
    read -p "Press Enter to finish (you can close this window afterward)." _
    exit 1
fi

if [ -d "$INSTALL_DIR/.git" ]; then
    echo "FokusKeeper is already downloaded at $INSTALL_DIR -- checking the reviewed release..."
    if ! git -C "$INSTALL_DIR" fetch --depth 1 origin "$RELEASE_COMMIT" || \
       ! git -C "$INSTALL_DIR" checkout --detach "$RELEASE_COMMIT"; then
        echo ""
        echo "Could not switch to the reviewed release (local changes in the way?)."
        echo "You can also just delete $INSTALL_DIR and double-click this"
        echo "file again for a completely fresh copy."
        read -p "Press Enter to finish (you can close this window afterward)." _
        exit 1
    fi
elif [ -e "$INSTALL_DIR" ]; then
    echo "$INSTALL_DIR already exists and isn't a FokusKeeper download."
    echo "Move or rename it, then double-click this file again."
    read -p "Press Enter to finish (you can close this window afterward)." _
    exit 1
else
    echo "Downloading the reviewed FokusKeeper release to $INSTALL_DIR ..."
    if ! git clone --no-checkout "$REPO_URL" "$INSTALL_DIR" || \
       ! git -C "$INSTALL_DIR" fetch --depth 1 origin "$RELEASE_COMMIT" || \
       ! git -C "$INSTALL_DIR" checkout --detach "$RELEASE_COMMIT"; then
        echo ""
        echo "Download failed -- check your internet connection and try again."
        read -p "Press Enter to finish (you can close this window afterward)." _
        exit 1
    fi
fi

if [ "$(git -C "$INSTALL_DIR" rev-parse HEAD 2>/dev/null)" != "$RELEASE_COMMIT" ]; then
    echo ""
    echo "Downloaded source did not match the reviewed release. Nothing was installed."
    read -p "Press Enter to finish (you can close this window afterward)." _
    exit 1
fi

echo ""
cd "$INSTALL_DIR" || exit 1
./install.sh
INSTALL_EXIT=$?

echo ""
if [ "$INSTALL_EXIT" -ne 0 ]; then
    echo "Setup hit a problem (see above). You can re-run it any time by"
    echo "double-clicking this file again."
fi
read -p "Press Enter to finish (you can close this window afterward)." _
