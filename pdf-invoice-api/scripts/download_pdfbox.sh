#!/usr/bin/env sh
set -eu

PDFBOX_VERSION="${PDFBOX_VERSION:-3.0.5}"
TARGET_DIR="${TARGET_DIR:-./vendor/pdfbox}"
TARGET_FILE="${TARGET_DIR}/pdfbox-app-${PDFBOX_VERSION}.jar"

mkdir -p "${TARGET_DIR}"
curl -fsSL "https://archive.apache.org/dist/pdfbox/${PDFBOX_VERSION}/pdfbox-app-${PDFBOX_VERSION}.jar" -o "${TARGET_FILE}"

echo "${TARGET_FILE}"
